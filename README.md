![SmartHouse Parental Control banner](docs/assets/banner.jpg)

# SmartHouse Parental Control

**Because parenting should have an API.**

*Powered by HAL Systems.*

Tired of negotiating "just five more minutes" for the seventh time tonight? Let Home Assistant keep score while you enjoy your coffee.

It tracks gaming budgets on Windows PCs, lets parents grant bonus minutes, and provides explicit controls when negotiations fail. No cloud account or recurring parental-control subscription required.

*Emotionally off duty, not legally. Please don't actually outsource parenting to a YAML file.*

## What can it do?

<table>
  <tr>
    <td width="42%" valign="middle">
      <a href="docs/features/gaming-budgets.md"><img src="docs/assets/illustrations/gaming-budgets.webp" width="320" alt="A cartoon king-dad showers plus-ten and plus-thirty gold gaming bonus coins upon two unimpressed children, with the family robot watching"></a>
    </td>
    <td valign="middle">
      <h3>⏱️ Gaming budgets — the clock doesn't negotiate.</h3>
      <p>Daily and weekly limits keep score. Feeling royal? Bestow an <strong>Add 30 minutes</strong> bonus on the young subjects — without changing their weekly limit. Even parental generosity has a terms-of-service agreement.</p>
      <p><a href="docs/features/gaming-budgets.md">How budgets and bonuses work</a></p>
    </td>
  </tr>
</table>

**🎮 Track applications — not just games.** Roblox, Minecraft, or any other application you decide deserves a spot on the scoreboard. The Home Assistant app list supports friendly names, while Windows reports safe foreground app identities. [How to track an application](docs/features/tracked-applications.md).

**🪄 Controls & automations — the magic that saves parental nerves.** Need an intervention now? **Lock PC** and **Terminate game** are explicit buttons, both smoke-tested on real hardware. The real superpower is **native Home Assistant automations**: design your own warning, grace period and (once the restriction signal is validated) consequence. Let the house handle the seventh "five more minutes" negotiation. **Automatic restriction enforcement is not yet validated or enabled by default.** [How controls and automations fit together](docs/features/parent-actions.md).

**🌙 AFK grind — investing in their future.** *Planned.* As responsible parents, we want our kids to succeed in life. And the loot isn't going to mine itself. With the display confirmed off, the game could keep grinding without charging new gaming minutes. Generous parents could also grant a **Screen idle bonus** for eligible idle time *before* the screen went off, without rewriting playtime history. The virtual economy never sleeps; thankfully, the kids can. [How Screen idle bonuses will work](docs/features/screen-idle-bonus.md).

**🧾 Budget overview — show your work.** *Planned.* A simple receipt: daily budget + weekend bonus + parent bonus + Screen idle bonus − measured gaming time = remaining time. [See the proposed Budget overview](docs/features/budget-overview.md).

**Development preview, not a finished family appliance.** The repository contains a Home Assistant integration and a Windows companion; feature availability depends on the deployed version. The app editor and other preview features still require complete end-to-end acceptance. Screen idle bonuses and the itemized Budget overview are **not implemented yet**. Do not turn on automatic enforcement until your own setup has been validated. [Release status and known limitations](docs/known_limitations.md).

## Want to get started?

**[Browse the documentation](docs/README.md)** for the beginner-friendly how-tos, screenshots when available, installation instructions, troubleshooting and engineering details. Or go directly to the [Windows deployment guide](docs/windows_deployment.md) and [Home Assistant setup](docs/ha_integration.md).

## The fine print (someone has to be the adult)

This is a family convenience tool, **not** tamper-proof security software or a substitute for parenting. A local administrator can stop it; missing telemetry can make measurements incomplete; terminating a game can lose unsaved progress. Keep MQTT private and restrict credentials. Do not disable Windows Smart App Control or Defender to install an unsigned development build. [Read the limitations](docs/known_limitations.md) and [privacy and protocol notes](docs/mqtt_protocol.md).

### Development disclosure: even the developer has been automated

Our reluctance to perform repetitive parenting duties apparently extends to software development, too.

After deciding to delegate gaming-time negotiations to Home Assistant, we thought: why stop there? So we recruited OpenAI's ChatGPT (including GPT-6) and Codex to help design, implement, review, test and document this project.

The human developer still makes the architectural decisions, defines the requirements and oversees testing on real hardware. Someone has to be responsible around here, and the AI refuses to sign school permission slips.

We follow trunk-based development, use automated tests and CI, and validate Windows service behavior on actual PCs. AI-assisted code is not a guarantee of correctness; bugs are still possible. Please report them.

**No AI subscription required:** AI is a development tool here, not a runtime dependency. The integration and Windows agent do not require ChatGPT, an OpenAI API key or an AI service to operate. Gaming telemetry stays within the configured MQTT and Home Assistant setup during normal operation.

In short: we automated the parenting, then automated part of the programming. Writing this disclaimer was, naturally, also AI-assisted.

Not affiliated with Home Assistant, HACS, Microsoft, Roblox or Minecraft. [Development and contribution details](docs/README.md#for-contributors).
