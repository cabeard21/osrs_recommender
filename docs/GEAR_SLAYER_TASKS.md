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
