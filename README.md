![SmartHouse Parental Control banner](docs/assets/banner.jpg)

# SmartHouse Parental Control

**Because parenting should have an API.**

*Powered by HAL Systems.*

Tired of negotiating "just five more minutes" for the seventh time tonight? Let Home Assistant keep score while you enjoy your coffee.

It tracks gaming budgets on Windows PCs, lets parents grant bonus minutes, and provides explicit controls when negotiations fail. No cloud account or recurring parental-control subscription required.

*Emotionally off duty, not legally. Please don't actually outsource parenting to a YAML file.*

## What can it do?

**⏱️ Gaming budgets — the clock doesn't negotiate.** Daily and weekly limits, measured gaming time, and a parent-controlled **Add 30 minutes** button. No more mental arithmetic at bedtime. [How budgets and bonuses work](docs/features/gaming-budgets.md).

**🎮 Track applications — not just games.** Roblox, Minecraft, or any other application you decide deserves a spot on the scoreboard. The Home Assistant app list supports friendly names, while Windows reports safe foreground app identities. [How to track an application](docs/features/tracked-applications.md).

**🔒 Manual controls — parental authority, now with buttons.** **Lock PC** and **Terminate game** are available as explicit parent actions, not a surprise automatic punishment. Both have passed limited real-device smoke tests. [What the controls do](docs/features/parent-actions.md).

**🌙 AFK grind support — because the loot won't farm itself.** *Planned.* Your kid has gone to bed; Roblox is still working the night shift. A future **Screen idle bonus** can let generous parents reward eligible idle minutes before the display went off. Strict parents can leave the bill as-is. The game can keep grinding with the screen off; the child doesn't get to appoint their avatar as the family accountant. [How Screen idle bonuses will work](docs/features/screen-idle-bonus.md).

**🧾 Budget overview — show your work.** *Planned.* A simple receipt: daily budget + weekend bonus + parent bonus + Screen idle bonus − measured gaming time = remaining time. [See the proposed Budget overview](docs/features/budget-overview.md).

**Development preview, not a finished family appliance.** The repository contains a Home Assistant integration and a Windows companion; feature availability depends on the deployed version. The app editor and other preview features still require complete end-to-end acceptance. Screen idle bonuses and the itemized Budget overview are **not implemented yet**. Do not turn on automatic enforcement until your own setup has been validated. [Release status and known limitations](docs/known_limitations.md).

## Want to get started?

**[Browse the documentation](docs/README.md)** for the beginner-friendly how-tos, screenshots when available, installation instructions, troubleshooting and engineering details. Or go directly to the [Windows deployment guide](docs/windows_deployment.md) and [Home Assistant setup](docs/ha_integration.md).

## The fine print (someone has to be the adult)

This is a family convenience tool, **not** tamper-proof security software or a substitute for parenting. A local administrator can stop it; missing telemetry can make measurements incomplete; terminating a game can lose unsaved progress. Keep MQTT private and restrict credentials. Do not disable Windows Smart App Control or Defender to install an unsigned development build. [Read the limitations](docs/known_limitations.md) and [privacy and protocol notes](docs/mqtt_protocol.md).

We automated the parenting negotiations, then wondered whether we could automate some of the programming too. So OpenAI's ChatGPT and Codex help design, implement, review, test and document the project.

The human developer still decides what ships and tests it on real hardware. **Someone has to be responsible around here, and the AI refuses to sign school permission slips.** AI assistance doesn't guarantee correctness, and **no AI subscription or OpenAI API key is required** to run the integration.

Not affiliated with Home Assistant, HACS, Microsoft, Roblox or Minecraft. [Development and contribution details](docs/README.md#for-contributors).
