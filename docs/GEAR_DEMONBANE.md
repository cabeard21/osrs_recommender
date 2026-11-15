# Demonbane ordinary attacks

Demonbane effects activate from the configured target's canonical `demon` trait.
No separate demon toggle or Slayer task is required. Slayer equipment still needs
the existing explicit task context. Results describe ordinary outgoing attacks
against fixed target statistics, rather than encounter kill times.

## Reviewed equipment and target context

Reviews preserve physical item identities, wear requirements, attack profiles,
tradeability and ammunition/autocast compatibility. Silverlight `2402/6745`,
Darklight `6746`, inactive Arclight `30305`, active Arclight `19675`, Emberlight
`29589`, Burning claws `29577`, Scorching bow `29591`, Purging staff `29594` and
Holy water `732` have separate physical reviews. Owned inactive Arclight does not
become owned active Arclight; this feature does not craft, charge or upgrade it.
Existing budget, exclusions and unowned-untradeable opt-in remain authoritative.

Silverlight, Darklight and inactive Arclight have 60% demonbane accuracy and
maximum-hit bonuses. Active Arclight and Emberlight have 70%; Burning claws has
5%. Scorching bow has 30%, with its damage bonus added to the imbued task-mask
15% bonus rather than multiplying those damage bonuses. Accuracy retains its
separate ordered calculation. Non-demons receive no demonbane benefit.

Holy water damages demons only. Its damage uses visible Ranged plus 10 and the
weapon's own Ranged strength; ordinary stance, equipment strength, prayer damage
and task-mask damage bonuses do not increase its maximum hit. Its demonbane
maximum-hit bonus is 60%. Accuracy is calculated separately. One vial is
destroyed per throw; Ava recovery does not apply.

Target effectiveness defaults to 100%. Reviewed exact NPC profiles include
Duke Sucellus at 70%, Yama at 120%, Ocellus/Xarth at 80% and Dreadnoth at 25%.
The modifier scales the demonbane bonus, rather than the whole attack. For
example, a 70% weapon bonus at Duke becomes 49%. Selected NPC effectiveness
cannot be overridden independently of its canonical profile.

Sources: [Silverlight](https://oldschool.runescape.wiki/w/Silverlight),
[Arclight](https://oldschool.runescape.wiki/w/Arclight),
[Burning claws](https://oldschool.runescape.wiki/w/Burning_claws),
[Scorching bow](https://oldschool.runescape.wiki/w/Scorching_bow),
[Holy water](https://oldschool.runescape.wiki/w/Holy_water), and
[reviewed target effectiveness implementation](https://github.com/weirdgloop/osrs-dps-calc/blob/74958b18f6559cf1bf58f7ac74e7a442a7ac8e2f/src/lib/BaseCalc.ts).

## Demonbane spells and Mark of Darkness

Inferior Demonbane requires 44 Magic, has base maximum hit 16, and consumes
three fire runes and one chaos rune per cast. Superior requires 62 Magic, has
base maximum hit 23, and consumes five fire runes and one soul rune. Dark
requires 82 Magic, has base maximum hit 30, and consumes seven fire runes and
two soul runes. These are non-elemental Arceuus spells; they do not inherit
elemental weaknesses or tome damage effects. Reviewed rune supply remains
equipment dependent. Spells cannot damage non-demons.

Arceuus spellbook access has no quest prerequisite. Superior and Dark require
confirmed *A Kingdom Divided* completion; Inferior does not. Explicit observed
spellbook restrictions and reviewed autocast weapon compatibility still apply.
Fixed selections and automatic combat-option searches use the same access gates.

Each configuration has `mark_of_darkness`, defaulting to false, including old
saved configurations. Enabled Mark is a maintained-buff assumption, not an
automatically optimized choice. It requires 59 Magic and *A Kingdom Divided*.
Its bonus and upkeep apply only if the selected attack is a demonbane spell;
another Auto selection retains the preference without paying irrelevant upkeep.

Ordinary demonbane spells have 20% bonus accuracy. Mark increases this to 40%
and adds 25% damage. Purging staff doubles these bonuses: 40% accuracy without
Mark, or 80% accuracy and 50% damage with Mark. Mark transforms each rolled
hit after the ordinary spell modifiers, with integer truncation; its expected
damage must not be approximated as a uniform distribution up to a boosted max.

Mark costs one soul and one cosmic rune per duration. Duration is three times
base Magic in ticks, multiplied by five when the selected weapon is Purging
staff. Future base-level overrides count; potion boosts and decay do not alter
duration. The model assumes refreshes with the selected weapon, without a
separate staff swap, and averages upkeep over continuous attacks. Its cast uses
zero attack ticks. Upkeep is time based and is normalized using the actual
attack interval for per-attack resource reporting.

Sources: [Demonbane spells](https://oldschool.runescape.wiki/w/Demonbane_spell),
[Arceuus spellbook](https://oldschool.runescape.wiki/w/Arceuus_spellbook),
[Purging staff](https://oldschool.runescape.wiki/w/Purging_staff),
[Mark of Darkness](https://oldschool.runescape.wiki/w/Mark_of_Darkness), and
[reviewed attack arithmetic](https://github.com/weirdgloop/osrs-dps-calc/blob/74958b18f6559cf1bf58f7ac74e7a442a7ac8e2f/src/lib/PlayerVsNPCCalc.ts).

## Resource uncertainty and scope

Active Arclight consumes one charge per successful normal hit, including attacks
against non-demons. Fully infused Arclight still consumes charges. Actual charge
balances and infusion are not inferred from ownership. Ancient-shard replacement
has no supported market quote, so its GP running cost is unavailable rather than
zero; DPS remains eligible. Missing rune or ammunition prices likewise make
costs unavailable without making an otherwise valid attack unavailable.

Special attacks, burning-claw special damage, defence-draining effects, survival,
movement, encounter rotations and shield/phase simulation are outside this
model. Holy water's ordinary-hit Defence drain is disclosed but does not change
the configured fixed target Defence. Existing unsupported encounter profiles
remain blocked. Respiratory systems need special one-hit/minimum-hit rules and
are blocked; Holy water against Nezikchened needs an excluded fixed damage rule
and is rejected. No fixed special-hit exception is approximated as a general
demonbane percentage bonus.

## Execution and validation

Python direct, prepared and cached scoring are the reference for compiled Cython
scoring. Supported effects must not trigger native fallback. Regression coverage
includes full optimizer output parity, native stage evidence, physical identity,
small-cap contextual candidate retention, Slayer stacking, target effectiveness,
spell access, Mark upkeep, unknown costs, API decoding and visible UI behavior.
Model and catalog revisions bind results to the reviewed effects and assumptions.
