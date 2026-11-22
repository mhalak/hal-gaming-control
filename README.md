![HAL Gaming Control banner](docs/assets/banner.png)

# HAL Gaming Control

**⚠️ HA 0.7.0 breaking preview:** the canonical Home Assistant domain is now `hal_gaming_control`. This replaces the old `smarthouse_gaming`, `parental` (0.6.0), and conflicting `parental_control` (0.6.1) domains. **Remove the previous integration before installing; no automatic migration or dual installation is supported.** [One-time clean-install instructions](docs/domain-clean-cut.md). Windows agent 0.2.6 and MQTT topics are unchanged. The shipped HAL icon lives under the new domain; Marketplace's pre-install thumbnail may require catalog indexing.

**Because parenting should have an API.**

*Powered by HAL Systems.*

Heard “just five more minutes” again? Let Home Assistant keep track while you enjoy your coffee.

Track gaming time on Windows PCs, set limits, give bonus minutes and use parent controls when needed.

**🏠 Local-first. Your home, your data.** We built our own Windows service so PCs report activity and receive controls through **your MQTT broker and Home Assistant**, with no third-party cloud service in the control loop. Core tracking, budgets and manual controls run on your local network; internet access may still be used for installation, updates or optional online data sources. [See how local mode works](docs/features/local-mode.md).

*Emotionally off duty, not legally. Please don't actually outsource parenting to a YAML file.*

## What can it do?

<a name="feature-local-mode"></a>

<table>
  <tr>
    <td width="132" valign="middle">
      <a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/local-mode.md"><img src="https://raw.githubusercontent.com/mhalak/hal-gaming-control/main/docs/assets/illustrations/local-mode.png" width="120" alt="HAL family house glowing in the dark, with children safe inside and game monsters beyond the fence"></a>
    </td>
    <td valign="middle">
      <h3>🏠 100% local — the monsters stay outside. So does the cloud.</h3>
      <p>We built our own <strong>Windows service</strong> so gaming activity and parent commands travel through <strong>your local MQTT broker and Home Assistant</strong>, not somebody else's cloud. No external control service, vendor account or subscription. The only boss battle is at home.</p>
      <p><a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/local-mode.md">How local mode works</a></p>
    </td>
  </tr>
</table>

<a name="feature-gaming-budgets"></a>

<table>
  <tr>
    <td width="132" valign="middle">
      <a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/gaming-budgets.md"><img src="https://raw.githubusercontent.com/mhalak/hal-gaming-control/main/docs/assets/illustrations/gaming-budgets-portrait.webp" width="120" alt="Cartoon king-dad tossing +10 and +30 gold coins to his two unimpressed blue-eyed children, next to a cheerful robot"></a>
    </td>
    <td valign="middle">
      <h3>⏱️ Gaming budgets — the clock doesn't negotiate.</h3>
      <p>The king can grant <strong>30 bonus minutes today</strong> or an additive <strong>Weekend bonus</strong> every Saturday and Sunday. The weekly budget, however, refuses to bow.</p>
      <p><a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/gaming-budgets.md">Budgets &amp; bonuses explained</a></p>
    </td>
  </tr>
</table>

<a name="feature-tracked-applications"></a>

<table>
  <tr>
    <td width="132" valign="middle">
      <a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/tracked-applications.md"><img src="https://raw.githubusercontent.com/mhalak/hal-gaming-control/main/docs/assets/illustrations/tracked-applications.webp" width="120" alt="🎮 Track applications — not just games.: HAL Systems family cartoon illustration"></a>
    </td>
    <td valign="middle">
      <h3>🎮 Track applications — not just games.</h3>
      <p>Choose what to track: Roblox, Minecraft or another app. Home Assistant gives each one a friendly name. <em>Development preview.</em></p>
      <p><a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/tracked-applications.md">How to track an application</a></p>
    </td>
  </tr>
</table>

<a name="feature-parent-actions"></a>

<table>
  <tr>
    <td width="132" valign="middle">
      <a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/parent-actions.md"><img src="https://raw.githubusercontent.com/mhalak/hal-gaming-control/main/docs/assets/illustrations/parent-actions.webp" width="120" alt="🪄 Controls &amp; automations — Automation Rules!: HAL Systems family cartoon illustration"></a>
    </td>
    <td valign="middle">
      <h3>🪄 Controls &amp; automations — Automation Rules!</h3>
      <p>Need a manual stop? Use <strong>Lock PC</strong> or <strong>Terminate game</strong>. The real magic is native Home Assistant automations: you set the reminders and rules, and let the robot handle “five more minutes.” <strong>Automatic enforcement still needs testing.</strong></p>
      <p><a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/parent-actions.md">How controls and automations fit together</a></p>
    </td>
  </tr>
</table>

<a name="feature-screen-idle-bonus"></a>

<table>
  <tr>
    <td width="132" valign="middle">
      <a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/screen-idle-bonus.md"><img src="https://raw.githubusercontent.com/mhalak/hal-gaming-control/main/docs/assets/illustrations/screen-idle-bonus.webp" width="120" alt="🌙 AFK grind — the loot won't mine itself.: HAL Systems family cartoon illustration"></a>
    </td>
    <td valign="middle">
      <h3>🌙 AFK grind — the loot won't mine itself.</h3>
      <p><strong>Planned.</strong> The child sleeps. The game keeps grinding. Screen-off time would stop counting, with an optional bonus for eligible idle time before the screen switched off.</p>
      <p><a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/screen-idle-bonus.md">How Screen idle bonuses will work</a></p>
    </td>
  </tr>
</table>

<a name="feature-budget-overview"></a>

<table>
  <tr>
    <td width="132" valign="middle">
      <a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/budget-overview.md"><img src="https://raw.githubusercontent.com/mhalak/hal-gaming-control/main/docs/assets/illustrations/budget-overview.webp" width="120" alt="🧾 Budget overview — the gaming-time audit.: HAL Systems family cartoon illustration"></a>
    </td>
    <td valign="middle">
      <h3>🧾 Budget overview — the gaming-time audit.</h3>
      <p><strong>Planned.</strong> Daily allowance + bonuses − time played = time left. Dad has the receipts. Mum would like the audit to end.</p>
      <p><a href="https://github.com/mhalak/hal-gaming-control/blob/main/docs/features/budget-overview.md">See the proposed Budget overview</a></p>
    </td>
  </tr>
</table>

**Development preview.** Features depend on the installed version. Screen idle bonuses and the itemized Budget Overview are **not implemented**. Don't enable automatic game closing or locking before testing on your PC. [What's ready and what's missing](docs/known_limitations.md).

## Want to get started?

**[Browse the guides](docs/README.md)** for setup and everyday use. Need more detail? See [Windows setup](docs/windows_deployment.md) and [Home Assistant setup](docs/ha_integration.md).

## The fine print (someone has to be the adult)

This is a family tool, **not** unbreakable security or a replacement for parenting. Missing data can leave gaps in playtime history; closing a game can lose unsaved progress. Keep your home network secure. **Never turn off Windows security protections** just to install it. [Known limitations](docs/known_limitations.md) · [Privacy details](docs/mqtt_protocol.md).

### Development disclosure: even the developer has been automated

Our reluctance to perform repetitive parenting duties apparently extends to software development, too.

After deciding to delegate gaming-time negotiations to Home Assistant, we thought: why stop there? So we recruited OpenAI's ChatGPT (including GPT-6) and Codex to help design, implement, review, test and document this project.

The human developer still makes the architectural decisions, defines the requirements and oversees testing on real hardware. Someone has to be responsible around here, and the AI refuses to sign school permission slips.

We follow trunk-based development, use automated tests and CI, and validate Windows service behavior on actual PCs. AI-assisted code is not a guarantee of correctness; bugs are still possible. Please report them.

**No AI subscription required:** AI is a development tool here, not a runtime dependency. The integration and Windows agent do not require ChatGPT, an OpenAI API key or an AI service to operate. Gaming telemetry stays within the configured MQTT and Home Assistant setup during normal operation.

In short: we automated the parenting, then automated part of the programming. Writing this disclaimer was, naturally, also AI-assisted.

Not affiliated with Home Assistant, HACS, Microsoft, Roblox or Minecraft. [Development and contribution details](docs/README.md#for-contributors).
