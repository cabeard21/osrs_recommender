# Slayer task equipment

Each ordinary combat configuration has an explicit `on_slayer_task` boolean,
defaulting to false. It asserts that its configured target counts toward the
player's current task. Assignments, location restrictions and remaining kills
are not imported or verified. Multi configurations can use different values.

Reviewed exact physical Black mask and Slayer helmet forms receive a 7/6 melee
accuracy/max-hit multiplier. Imbued forms additionally receive 23/20 ranged and
magic accuracy/max-hit multipliers. Effects require the appropriate equipped
item and task context. Normal stats remain unchanged. Physical ownership,
imbues, charge forms, exclusions and acquisition restrictions are preserved.

Magic Dart requires 50 Magic, 55 Slayer and a reviewed compatible Slayer staff.
Its base maximum is `10 + Magic // 10`; Slayer's staff (e) on task uses
`13 + Magic // 6`. Subsequent damage modifiers, including an imbued mask,
apply afterward with integer truncation. Magic Dart is non-elemental and uses
one death rune and four mind runes per cast. These spells are not powered attacks.

The native Cython candidate scorer calculates the task multipliers and enhanced
Magic Dart base directly. Python reference/direct/prepared/cached paths follow
the same arithmetic. Task context travels through workers, Auto, refinements,
fixed comparisons and fingerprints. Newly supported effects must not trigger
native fallback. Formula order is pinned to
[Weird Gloop's calculator](https://github.com/weirdgloop/osrs-dps-calc/blob/74958b18f6559cf1bf58f7ac74e7a442a7ac8e2f/src/lib/PlayerVsNPCCalc.ts).

Enchanted staff preparation preserves the actual owned form and discloses that
actual charges are unknown. An explicit ordinary staff lock stays ordinary.
Enchantment is a consumable preparation, outside the gear purchase budget;
expected running consumption on task is `accuracy / 2500` enchantments per
Magic Dart cast. Missing resource prices make costs unavailable. No charges
are consumed for off-task or other-spell casts. Rune costs still apply on a
splash. Sources: [Magic Dart](https://oldschool.runescape.wiki/w/Magic_Dart),
[Slayer's staff (e)](https://oldschool.runescape.wiki/w/Slayer%27s_staff_%28e%29).

Black mask's random defence drain, helmet protection, assignment length and
Slayer XP effects are outside this ordinary outgoing-damage model. Existing
unsupported mechanics, including Salve effects, retain their existing policy.

## Turoths and leafy targets

The four ordinary Turoth variants (Baby, Child, Mum and Dad), Spiked Turoth,
both Kurask variants and King kurask support ordinary outgoing attacks.
Catalog target traits enforce their shared leafy restriction: melee requires
a leaf-bladed spear, sword or battleaxe; ranged requires a supported compatible
bow or crossbow actually firing broad ammunition; magic requires Magic Dart
with a reviewed Slayer's staff or Slayer's staff (e). Merely equipping broad
ammunition with a thrown or self-contained ranged weapon does not qualify.
Selecting a Turoth requires 55 Slayer; Kurasks require 70 Slayer. Unknown levels
block the request; authorized future skill overrides use their projected levels.
Assignment, location access and superior spawning are not inferred.

Reviewed exact equipment forms are leaf-bladed spear `4158`, sword `11902`,
battleaxe `20727`, broad arrows `4160`, Seeking broad arrows `33601`, broad bolts
`11875` and amethyst broad bolts `21316`. The spear and sword require 50 Attack,
the battleaxe 65 Attack; all three require 55 Slayer. Both arrow forms require
50 Ranged and 55 Slayer. Broad bolts require 61 Ranged and 55 Slayer; amethyst
broad bolts require 61 Ranged and 65 Slayer. Crafting requirements are separate
from wear gates. Sources: [Turoth](https://oldschool.runescape.wiki/w/Turoth),
[Kurask](https://oldschool.runescape.wiki/w/Kurask),
[Slayer equipment](https://oldschool.runescape.wiki/w/Slayer_equipment).

The leaf-bladed battleaxe multiplies maximum damage by `47/40` against leafy
targets, after the task-mask multiplier, truncating at each step. This damage
bonus also applies off task; it does not add accuracy. Seeking broad arrows add
their reviewed +20 ranged accuracy only when fired by a compatible bow. Each
accurate raw hitsplat below 3 is raised to 3 before flat armour; misses remain
zero. This is a clamped distribution, not a uniform roll from 3 to maximum.
Source: [Seeking broad arrows](https://oldschool.runescape.wiki/w/Seeking_broad_arrows).

The native Cython scorer enforces the same legal combinations and calculates
both damage effects directly. Python direct, prepared and cached calculations
remain the parity reference; supported acceptance fixtures require zero native
fallbacks. Applied effect reports appear independently of Slayer task effects.

Physical ownership and existing acquisition policy remain authoritative. The
spear and both broad-arrow forms are untradeable; unowned forms require the
existing untradeable opt-in outside owned mode. Replacement prices unavailable
from supported price facts leave running costs unavailable, rather than zero.
This coverage does not price shop purchases or crafting recipes, or add healing,
survival, special attacks, encounter downtime or superior-spawn simulation.
