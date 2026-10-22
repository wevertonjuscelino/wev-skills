#!/usr/bin/env bash
# wev-skills installer: bash install.sh [flags]   (bash install.sh --help)
# Thin on purpose: it asks, then calls the wev CLI, which holds the rules.
# Questions are read from /dev/tty because under `curl | bash` stdin is this script.
set -euo pipefail

REPO="wevertonjuscelino/wev-skills"
API_URL="https://api.github.com/repos/$REPO/releases/latest"
GIT_URL="https://github.com/$REPO.git"
MARKET="wev-skills-marketplace"
PLUGIN="wev-skills@$MARKET"
LICENCE_TITLE="PolyForm Noncommercial License 1.0.0"
LICENCE_URL="https://polyformproject.org/licenses/noncommercial/1.0.0"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/wev-skills"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/wev-skills"
YES=0 PURGE=0 UNINSTALL=0 SOURCE="" HARNESS_ARG="" JEV_FLAG=ask REA_ARG="" L_ARG=""
TMP="" PY="" WEV="" MKT_DIR="" OUT="" RC=0 ANS="" ROWS="" NEXT="" FAILED=0 SKIP_REA=0 CHOSEN=""
OLD_PY=0 SHADOWED=0 STTY_SAVED=""
case "${LANG:-}" in pt*) L="pt-BR" ;; *) L="en" ;; esac

# The message table: one line per key, English (en) and Brazilian Portuguese (pt) side by side.
# bash 3.2 has no associative arrays; a case keeps the two key sets identical by construction.
msg() {
  local en pt
  case "$1" in
    no_tty) en="No terminal to ask on. Run this from a terminal, or answer for me with --yes (plus --harness, --jev or --no-jev, --rea-mode)."
            pt="Não há terminal para perguntar. Rode num terminal, ou responda por mim com --yes (mais --harness, --jev ou --no-jev, --rea-mode)." ;;
    lang_ask) en="Language / Idioma [en/pt-BR] (default %s): " pt="Language / Idioma [en/pt-BR] (padrão %s): " ;;
    licence) en="License: %s (%s). Noncommercial use only." pt="Licença: %s (%s). Somente uso não comercial." ;;
    licence_ask) en="Install wev-skills under this license? [y/N] " pt="Instalar o wev-skills sob esta licença? [s/N] " ;;
    declined) en="License not confirmed. Nothing was installed." pt="Licença não confirmada. Nada foi instalado." ;;
    fail) en="Cannot continue: %s" pt="Não é possível continuar: %s" ;;
    bad_os) en="Only macOS and Linux are supported." pt="Só macOS e Linux são suportados." ;;
    missing_tool) en="%s is required and was not found. Install it and run this again." pt="%s é necessário e não foi encontrado. Instale e rode de novo." ;;
    py_missing) en="Python 3.14 or newer was not found." pt="Python 3.14 ou mais novo não foi encontrado." ;;
    empty_key) en="No key was entered." pt="Nenhuma chave foi digitada." ;;
    bad_tag) en="Unexpected release tag: %s" pt="Tag de release inesperada: %s" ;;
    ver_mismatch) en="Installed version %s does not match release %s." pt="A versão instalada %s não corresponde à release %s." ;;
    no_source) en="There is no bin/wev in %s." pt="Não há bin/wev em %s." ;;
    old_python) en="python3 on your PATH is older than 3.14. The harness hooks start wev through 'env python3', so put a Python 3.14 first on PATH or the hooks will not run." pt="O python3 do seu PATH é anterior ao 3.14. Os hooks dos harnesses iniciam o wev por 'env python3'; ponha um Python 3.14 primeiro no PATH ou os hooks não vão rodar." ;;
    shadowed) en="TYPESAFE_API_KEY is exported in your environment and will win over the stored key." pt="TYPESAFE_API_KEY está exportada no seu ambiente e vai valer mais que a chave guardada." ;;
    fin_fail) en="Finished with %s failures (see the rows above)." pt="Terminou com %s falhas (veja as linhas acima)." ;;
    un_keep) en="Something failed above, so %s was kept. Fix it and run --uninstall again." pt="Algo falhou acima, então %s foi mantido. Corrija e rode --uninstall de novo." ;;
    un_nowev) en="Cannot run wev to undo its registrations (Python or wev missing), so %s was kept." pt="Não consigo rodar o wev para desfazer os registros (falta Python ou wev), então %s foi mantido." ;;
    o_harness) en="the harness decides" pt="o harness decide" ;;
    o_jev) en="JEV decides" pt="o JEV decide" ;;
    offer) en="%s is missing. I can run this command for you: %s" pt="Falta %s. Posso rodar este comando para você: %s" ;;
    offer_ask) en="Run it? [y/N] " pt="Rodar? [s/N] " ;;
    stop_cmd) en="%s is missing. With --yes I do not install system packages; run this, then run the installer again: %s"
              pt="Falta %s. Com --yes eu não instalo pacotes do sistema; rode isto e depois rode o instalador de novo: %s" ;;
    harness_ask) en="Install into %s? [Y/n] " pt="Instalar no %s? [S/n] " ;;
    jev_ask) en="Use JEV (decision model, needs an API key)? [y/N] " pt="Usar o JEV (modelo de decisão, exige chave de API)? [s/N] " ;;
    key_prompt) en="JEV API key (input hidden): " pt="Chave de API do JEV (digitação oculta): " ;;
    retry_ask) en="Enter the key again? [y/N] " pt="Digitar a chave de novo? [s/N] " ;;
    wev_fail) en="A wev command failed: wev %s" pt="Um comando do wev falhou: wev %s" ;;
    build_ask) en="Build the rea container image now? It can take minutes. [Y/n] " pt="Construir a imagem de contêiner do rea agora? Pode levar minutos. [S/n] " ;;
    codex_mcp) en="Register rea in Codex yourself: codex mcp add rea -- %s %s rea serve" pt="Registre o rea no Codex você mesmo: codex mcp add rea -- %s %s rea serve" ;;
    sum_head) en="Summary" pt="Resumo" ;;
    sum_line) en="%s: %s" pt="%s: %s" ;;
    sum_next) en="Next steps for you:" pt="Próximos passos, com você:" ;;
    sum_source) en="Installed from a local source, not self-updating." pt="Instalado de uma fonte local, sem autoatualização." ;;
    un_removed) en="Removed: %s" pt="Removido: %s" ;;
    un_kept) en="Kept: %s" pt="Mantido: %s" ;;
    un_ask) en="Also remove %s (key file and user configuration)? [y/N] " pt="Remover também %s (arquivo da chave e configuração do usuário)? [s/N] " ;;
    st_ok) en="done" pt="feito" ;;
    st_skip) en="skipped" pt="pulado" ;;
    st_fail) en="failed" pt="falhou" ;;
    r_notfound) en="CLI not found" pt="CLI não encontrado" ;;
    r_declined) en="declined" pt="recusado" ;;
    r_nonode) en="Node.js missing" pt="falta o Node.js" ;;
    r_noimage) en="rea is not installed, so there is no image to build" pt="o rea não está instalado, então não há imagem para construir" ;;
    r_see) en="see the output above" pt="veja a saída acima" ;;
    r_off) en="JEV is off" pt="JEV desligado" ;;
    r_probe) en="JEV is off, the probe failed (details above)" pt="JEV desligado, o teste falhou (detalhes acima)" ;;
  esac
  if [ "$L" = pt-BR ]; then printf '%s' "$pt"; else printf '%s' "$en"; fi
}
# shellcheck disable=SC2059  # the format comes from the message table above, never from input
say() { local f; f=$(msg "$1"); shift; printf -- "$f\n" "$@"; }
die() { local code=$1; shift; say "$@" >&2; exit "$code"; }
have() { command -v "$1" >/dev/null 2>&1; }
restore_tty() { if [ -n "$STTY_SAVED" ]; then stty "$STTY_SAVED" </dev/tty 2>/dev/null || true; fi; }
cleanup() { restore_tty; if [ -n "$TMP" ]; then rm -rf "$TMP"; fi; }

usage() {
  cat <<'EOF'
Usage: bash install.sh [flags]
  --yes                      answer yes; no JEV unless --jev, no system packages, uninstall keeps the config dir
  --lang en|pt-BR            message language (default: from LANG)
  --harness LIST             claude,codex,gemini,opencode (default: the ones found)
  --jev | --no-jev           use JEV (asks for the key) or not (default: ask)
  --rea-mode isolated|direct how rea runs (default: isolated when docker is found)
  --source DIR               use DIR/bin/wev instead of downloading the latest release
  --uninstall [--purge]      remove what the installer put in place (--purge: config too)
  --help                     show this text
EOF
}

opt() { [ "$#" -ge 2 ] && [ -n "$2" ] || { usage >&2; exit 2; }; }
parse() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes) YES=1 ;;
      --jev) JEV_FLAG=yes ;;
      --no-jev) JEV_FLAG=no ;;
      --uninstall) UNINSTALL=1 ;;
      --purge) PURGE=1 ;;
      --lang) opt "$@"; L_ARG=$2; shift ;;
      --harness) opt "$@"; HARNESS_ARG=$2; shift ;;
      --rea-mode) opt "$@"; REA_ARG=$2; shift ;;
      --source) opt "$@"; SOURCE=$2; shift ;;
      --help | -h) usage; exit 0 ;;
      *) usage >&2; exit 2 ;;
    esac
    shift
  done
  case "$L_ARG" in "" | en | pt-BR) ;; *) usage >&2; exit 2 ;; esac
  case "$REA_ARG" in "" | isolated | direct) ;; *) usage >&2; exit 2 ;; esac
  local names='(claude|codex|gemini|opencode)'
  [[ -z $HARNESS_ARG || $HARNESS_ARG =~ ^$names(,$names)*$ ]] || { usage >&2; exit 2; }
}

# One question: the prompt goes to the terminal and the answer comes from it, never from stdin.
ask_line() {
  # shellcheck disable=SC2059
  { printf -- "$(msg "$1")" "${@:2}" >/dev/tty; IFS= read -r ANS </dev/tty; } 2>/dev/null || die 2 no_tty
}
confirm() { # confirm KEY y|n [args]: --yes answers yes
  [ "$YES" = 1 ] && return 0
  ask_line "$1" "${@:3}"
  case "$ANS" in [yYsS]*) return 0 ;; "") [ "$2" = y ] ;; *) return 1 ;; esac
}
row() { # row STATUS-KEY NAME [DETAIL-KEY]
  local detail=""
  if [ -n "${3:-}" ]; then detail=$(msg "$3"); fi
  ROWS="$ROWS$(printf '  %-9s %-14s %s' "$(msg "$1")" "$2" "$detail")"$'\n'
}
row_rc() { # a row for the last wev call: done, or failed with its output shown
  if [ "$RC" -eq 0 ]; then row st_ok "$1"; else printf '%s\n' "$OUT" >&2; row st_fail "$1" r_see; FAILED=$((FAILED + 1)); fi
}
jval() { "$PY" -I -c 'import json, sys
v = json.load(sys.stdin)
for k in sys.argv[1:]:
    v = v.get(k) if isinstance(v, dict) else None
print("\n".join(map(str, v)) if isinstance(v, list) else "" if v is None else v)' "$@"; }
wevc() { RC=0; OUT=$("$PY" "$WEV" --lang "$L" "$@" </dev/null) || RC=$?; }
wevx() { wevc "$@"; if [ "$RC" -ne 0 ]; then printf '%s\n' "$OUT" >&2; die 1 wev_fail "$*"; fi; }
note_steps() { # add the next_steps of the last wev call to NEXT
  local line
  while IFS= read -r line; do
    if [ -n "$line" ]; then NEXT="$NEXT  - $line"$'\n'; fi
  done <<<"$(printf '%s' "$OUT" | jval next_steps)"
}
py_ok() { [ "$("$1" -I -c 'import sys; print(sys.version_info >= (3, 14))' 2>/dev/null)" = True ]; }
find_python() {
  local c
  for c in python3.14 python3 python; do
    if have "$c" && py_ok "$c"; then PY=$(command -v "$c"); return 0; fi
  done
  return 1
}
installer_cmd() { # the one known installer command found on this machine ($1 = python|node)
  if [ "$1" = python ] && have uv; then echo "uv python install 3.14"
  elif have brew; then if [ "$1" = python ]; then echo "brew install python"; else echo "brew install node"; fi
  elif have apt-get; then echo "sudo apt-get install -y python3 nodejs npm"
  elif have dnf; then echo "sudo dnf install -y python3 nodejs"
  fi
}
run_installer() { # only these literal commands can run
  case "$1" in
    "uv python install 3.14") uv python install 3.14 ;;
    "brew install python") brew install python ;;
    "brew install node") brew install node ;;
    "sudo apt-get install -y python3 nodejs npm") sudo apt-get install -y python3 nodejs npm ;;
    "sudo dnf install -y python3 nodejs") sudo dnf install -y python3 nodejs ;;
  esac
}
offer_install() { # 0 when it installed; --yes stops and names the command
  local cmd
  cmd=$(installer_cmd "$1")
  if [ -z "$cmd" ]; then return 1; fi
  if [ "$YES" = 1 ]; then die 1 stop_cmd "$1" "$cmd"; fi
  say offer "$1" "$cmd"
  confirm offer_ask n && run_installer "$cmd"
}
check_system() {
  local c
  case "$(uname -s)" in Darwin | Linux) ;; *) die 1 bad_os ;; esac
  if [ -z "$SOURCE" ]; then
    for c in git curl; do have "$c" || die 1 missing_tool "$c"; done
  fi
  find_python || { offer_install python && find_python; } || die 1 py_missing
  if ! have python3 || ! py_ok python3; then OLD_PY=1; fi
  if ! have node || ! have npm; then
    if offer_install node && have node; then :; else SKIP_REA=1; fi
  fi
}
pick_harnesses() {
  local h wanted=${HARNESS_ARG:-claude,codex,gemini,opencode}
  for h in claude codex gemini opencode; do
    case ",$wanted," in *",$h,"*) ;; *) continue ;; esac
    if ! have "$h"; then row st_skip "$h" r_notfound; continue; fi
    if [ -z "$HARNESS_ARG" ] && ! confirm harness_ask y "$h"; then row st_skip "$h" r_declined; continue; fi
    CHOSEN="$CHOSEN $h "
  done
}
bootstrap() {
  local tag ver clone="$TMP/clone"
  if [ -n "$SOURCE" ]; then
    WEV="$SOURCE/bin/wev"; MKT_DIR=$SOURCE
    [ -x "$WEV" ] || die 1 no_source "$SOURCE"
    return
  fi
  tag=$(curl -fsSL "$API_URL" | jval tag_name) || die 1 fail "$API_URL"
  [[ $tag =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 1 bad_tag "$tag"
  git clone --quiet --depth 1 --branch "$tag" "$GIT_URL" "$clone" || die 1 fail "git clone $tag"
  "$PY" "$clone/bin/wev" --lang "$L" skills update wev-skills </dev/null >"$TMP/boot.out" \
    || { cat "$TMP/boot.out" >&2; die 1 fail "skills update wev-skills"; }
  MKT_DIR="$DATA/third-party/wev-skills/current"; WEV="$MKT_DIR/bin/wev"
  wevx version
  ver=$(printf '%s' "$OUT" | jval version)
  [ "$ver" = "${tag#v}" ] || die 1 ver_mismatch "$ver" "${tag#v}"
}
store_key() {
  local key
  set +x # a trace would print the key
  STTY_SAVED=$(stty -g </dev/tty 2>/dev/null) || STTY_SAVED=""
  # shellcheck disable=SC2059
  { printf -- "$(msg key_prompt)" >/dev/tty; IFS= read -rs key </dev/tty; } 2>/dev/null || die 2 no_tty
  restore_tty; printf '\n' >/dev/tty 2>/dev/null || true
  [ -n "$key" ] || die 1 empty_key
  # printf is a builtin and the pipe is stdin: the key is in no argv, no env var, no file
  if ! printf '%s\n' "$key" | "$PY" "$WEV" --lang "$L" jev key set >"$TMP/key.out"; then
    cat "$TMP/key.out" >&2; die 1 wev_fail "jev key set"
  fi
  # an exported TYPESAFE_API_KEY shadows the stored key (the probe below ignores it)
  if [ "$(jval shadowed_by_env <"$TMP/key.out")" = True ]; then SHADOWED=1
  elif [ "$(jval key_source <"$TMP/key.out")" != env_file ]; then die 1 wev_fail "jev key set"; fi
}
probe_jev() {
  printf '%s\n' '{"q": {"type": "noul", "instructions": "Is this a connectivity probe?"}}' >"$TMP/q.json"
  RC=0
  OUT=$(env -u TYPESAFE_API_KEY "$PY" "$WEV" --lang "$L" jev ask --questions "$TMP/q.json" --state "installer probe" </dev/null) || RC=$?
  if [ "$RC" -ne 0 ]; then printf '%s\n' "$OUT" >&2; return 1; fi
}
write_user_config() { # $1 = 1 when JEV is on; touches language and decision.provider only
  local file="$CONF/wev.config.json"
  ( umask 077; mkdir -p "$CONF"; trap 'rm -f "$file.tmp"' EXIT
    "$PY" -I -c 'import json, os, sys
path, lang, jev = sys.argv[1:4]
c = json.load(open(path)) if os.path.isfile(path) else {}
c["language"] = lang
d = c.pop("decision", None)
d = d if isinstance(d, dict) else {}
d.pop("provider", None)
if jev == "1":
    d["provider"] = "jev"
if d:
    c["decision"] = d
print(json.dumps(c, indent=2))' "$file" "$L" "$1" >"$file.tmp"
    mv "$file.tmp" "$file"; chmod 600 "$file" )
  wevx config validate "$file"
}
setup_jev() {
  local on=0 tries=0
  case "$JEV_FLAG" in
    yes) on=1 ;;
    ask) if [ "$YES" = 0 ] && confirm jev_ask n; then on=1; fi ;;
  esac
  if [ "$on" = 1 ]; then
    on=0
    while [ "$tries" -lt 2 ]; do
      store_key
      if probe_jev; then on=1; break; fi
      tries=$((tries + 1))
      if [ "$YES" = 1 ] || ! confirm retry_ask n; then break; fi
    done
  fi
  write_user_config "$on"
  if [ "$on" = 1 ]; then row st_ok JEV; elif [ "$tries" -gt 0 ]; then row st_skip JEV r_probe; else row st_skip JEV r_off; fi
}
third_party() {
  local s
  for s in rea agent-skills; do
    if [ "$s" = rea ] && [ "$SKIP_REA" = 1 ]; then row st_skip rea r_nonode; continue; fi
    wevc skills update "$s"; row_rc "$s"
  done
  wevc skills activate; row_rc activate
}
setup_rea() {
  local mode=$REA_ARG
  if [ "$SKIP_REA" = 1 ]; then return; fi
  if [ -z "$mode" ]; then if have docker; then mode=isolated; else mode=direct; fi; fi
  wevx rea mode "$mode"
  row st_ok "rea-$mode"
  if [ "$mode" = direct ]; then return; fi
  wevx rea status
  if [ -z "$(printf '%s' "$OUT" | jval version)" ]; then row st_skip rea-image r_noimage; return; fi
  if confirm build_ask y; then wevx rea build-image; row st_ok rea-image; else row st_skip rea-image r_declined; fi
}
register_claude() {
  RC=0; OUT=$(claude plugin marketplace add "$MKT_DIR" </dev/null 2>&1) || RC=$?
  printf '%s\n' "$OUT"
  if [ "$RC" -eq 0 ]; then
    OUT=$(claude plugin install "$PLUGIN" </dev/null 2>&1) || RC=$?
    printf '%s\n' "$OUT"
  fi
  row_rc claude
}
register_harnesses() {
  local h
  for h in claude codex gemini opencode; do
    case "$CHOSEN" in *" $h "*) ;; *) continue ;; esac
    if [ "$h" = claude ]; then register_claude; continue; fi
    wevc harness install --target "$h" --wev "$WEV"; row_rc "$h"
    if [ "$RC" -ne 0 ]; then continue; fi
    note_steps
    if [ "$h" = codex ]; then NEXT="$NEXT  - $(say codex_mcp "$PY" "$WEV")"$'\n'; fi
  done
}

summary() {
  local o
  say sum_head
  wevx version; say sum_line wev-skills "$(printf '%s' "$OUT" | jval version)"
  wevx jev status; o=$(printf '%s' "$OUT" | jval orchestration)
  case "$o" in harness) o=$(msg o_harness) ;; jev) o=$(msg o_jev) ;; esac
  say sum_line JEV "$o"
  wevx rea status; say sum_line rea "$(printf '%s' "$OUT" | jval mode)"
  wevx skills list
  say sum_line skills "$(printf '%s' "$OUT" | "$PY" -I -c 'import json, sys
print(", ".join("%s %s" % (s["name"], s["active"]) for s in json.load(sys.stdin)["sources"] if s["active"]))')"
  printf '%s' "$ROWS"
  if [ -n "$NEXT" ]; then say sum_next; printf '%s' "$NEXT"; fi
  if [ -n "$SOURCE" ]; then say sum_source; fi
  if [ "$OLD_PY" = 1 ]; then say old_python; fi
  if [ "$SHADOWED" = 1 ]; then say shadowed; fi
  if [ "$FAILED" -gt 0 ]; then say fin_fail "$FAILED"; fi
  say licence "$LICENCE_TITLE" "$LICENCE_URL"
}

do_uninstall() {
  local t bad=0
  find_python || true
  if [ -n "$SOURCE" ]; then WEV="$SOURCE/bin/wev"; else WEV="$DATA/third-party/wev-skills/current/bin/wev"; fi
  if [ -x "$WEV" ] && [ -n "$PY" ]; then
    for t in codex gemini opencode; do
      if [ ! -f "$DATA/harness/$t/manifest.json" ]; then continue; fi
      wevc harness uninstall --target "$t"
      if [ "$RC" -eq 0 ]; then say un_removed "harness $t"; else printf '%s\n' "$OUT" >&2; bad=1; fi
    done
    if [ -e "$DATA/third-party/agent-skills/current" ]; then
      wevc skills deactivate
      if [ "$RC" -ne 0 ]; then printf '%s\n' "$OUT" >&2; bad=1; fi
    fi
  elif [ -d "$DATA" ]; then
    say un_nowev "$DATA" >&2; return 1
  fi
  if have claude; then
    claude plugin uninstall wev-skills </dev/null || bad=1
    claude plugin marketplace remove "$MARKET" </dev/null || bad=1
  fi
  if [ "$bad" = 1 ]; then say un_keep "$DATA" >&2; return 1; fi
  rm -rf "$DATA"; say un_removed "$DATA"
  if [ ! -d "$CONF" ]; then return; fi
  if [ "$PURGE" = 1 ] || { [ "$YES" = 0 ] && confirm un_ask n "$CONF"; }; then
    rm -rf "$CONF"; say un_removed "$CONF"
  else
    say un_kept "$CONF"
  fi
}

main() {
  parse "$@"
  if [ -n "$SOURCE" ]; then SOURCE=$(CDPATH='' cd -- "$SOURCE" >/dev/null && pwd) || die 1 no_source "$SOURCE"; fi
  TMP=$(mktemp -d)
  trap cleanup EXIT
  trap 'exit 130' INT TERM HUP
  cd -- "$TMP" # never run wev from the person's directory: its wev.config.json is not ours to trust
  if [ -n "$L_ARG" ]; then L=$L_ARG
  elif [ "$YES" = 0 ]; then
    ask_line lang_ask "$L"
    case "$ANS" in en | pt-BR) L=$ANS ;; esac
  fi
  if [ "$UNINSTALL" = 1 ]; then do_uninstall; return; fi
  say licence "$LICENCE_TITLE" "$LICENCE_URL"
  confirm licence_ask n || die 1 declined
  check_system
  pick_harnesses
  bootstrap
  setup_jev
  third_party
  setup_rea
  register_harnesses
  summary
  if [ "$FAILED" -gt 0 ]; then return 1; fi
}

main "$@"
