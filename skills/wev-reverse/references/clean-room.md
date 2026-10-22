# Clean-room study of another product

Use this when the goal is to learn how a feature of someone else's product behaves and is built, and to write a specification the person can build from. Documented only: these are instructions for you. Nothing in wev checks them, and nothing here is legal advice. The person carries authorization and legal responsibility, as rea's DISCLAIMER says.

## What you may observe

- Behavior: what the feature does for a given input, what the user sees, what messages and states appear.
- Public bundles and public files that the product serves to every user, and the structure of the public network traffic of the person's own session.
- Public documentation, release notes and standards the product follows.

Stop and ask the person when the work would need more than that: a protection, a license check, DRM, a private or authenticated API that the person has no right to use, or any step that touches a live service in a way the person did not authorize.

## What the specification contains

- Behaviors: inputs, outputs, states, error cases, limits, each with the observation that supports it.
- Architecture in your own words: components, data flow, formats and protocols at the level of what is observable, with the evidence path for each point.
- Open questions and what could not be observed.
- A list of what was deliberately left out.

## What it never contains

- Copied code, decompiled code, pseudocode transcribed line by line, copied assets (text, images, fonts, icons, data files) or copied identifiers that carry no meaning of their own.
- Keys, tokens, endpoints that are private to the product, or instructions to call them.
- Any design that makes the person's product depend on the target's private APIs.

## Separation of roles

Two passes keep the result clean. The observation pass produces notes and the evidence bundle. The specification pass describes behavior and structure from those notes only, without pasting tool output. When a reviewer or a second agent is available, the person who will implement should read the specification and not the raw tool output.

## Handing over

Give the person the specification, the evidence bundle path and the list of open questions. The decision to build, and whether the result is acceptable under the terms that apply, is theirs.
