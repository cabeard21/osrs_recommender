# Vampyre targets in the Gear Optimizer

Select the NPC variant in the target picker. Its tier determines which attacks can damage it.
The optimizer compares legal weapons, ammunition, rings and armour under the role's equipment
locks, account requirements and acquisition budget. Slayer bonuses require explicit task context.

| Tier | Reviewed targets | Effect on attacks |
| --- | --- | --- |
| 1 | Feral Vampyre, Vampyre Juvenile, Kroy | All otherwise legal attacks work. Ordinary silver gains 10% damage. Specialist weapons use their own damage bonus. |
| 2 | Vampyre Juvinate | Ordinary silver hits cap at 10. With Efaritay's aid, ordinary attacks, including ordinary silver, deal half damage per hit. The Rod of Ivandis and the tier 3 weapons deal uncapped damage. |
| 3 | Vyrewatch, Vyrewatch Sentinel, regular and blood-starved Venators, ordinary Ancient feral vyres | Use an Ivandis flail, plain blisterwood sickle, blisterwood flail, Hallowed flail or Sunspear in melee, or throw blisterwood stakes. Efaritay's aid requires an attack that already qualifies. |

Silver bolts qualify when fired by a compatible crossbow. Spells use their own attack source,
including when cast with a flail. Specialist damage bonuses apply once. Efaritay's aid grants 15%
accuracy on qualifying silver attacks and 10% damage on uncapped attacks. The ring's damage
bonus is applied before the weapon bonus, flooring at each step on each rolled hit.
Tier 2 uses the calculator maintainers' tested silver cap and their later correction for uncapped
weapons. The Wiki's general silver equipment table describes a different tier 2 outcome.
[Vampyre effects](https://oldschool.runescape.wiki/w/Vampyre_%28attribute%29) ·
[Silver equipment table](https://oldschool.runescape.wiki/w/Silver_weaponry) ·
[Tier 2 silver cap](https://github.com/weirdgloop/osrs-dps-calc/pull/671) ·
[Tier 2 correction](https://github.com/weirdgloop/osrs-dps-calc/pull/1012) ·
[Reference calculation](https://github.com/weirdgloop/osrs-dps-calc/blob/3da927f4280c73154fa59e4e90eb374af5123d32/src/lib/PlayerVsNPCCalc.ts)

## Access and supplies

The target notes identify quest and Slayer requirements. Ordinary Juvenile and Juvinate DPS
covers attacks before retreat. A regular Venator needs 74 Slayer and completion of *The Blood
Moon Rises*. Off-task access costs 30 Stymphike feathers per kill. This fee is separate from
gear upkeep per attack. Quest bosses and Nightmare Zone copies have individual restrictions.
Kroy is selectable at any quest progress. His DPS uses base combat stats and excludes scripted
encounter mechanics.
[Venators](https://oldschool.runescape.wiki/w/Venator) ·
[Vampyre Juvinates](https://oldschool.runescape.wiki/w/Vampyre_Juvinate) ·
[Kroy](https://oldschool.runescape.wiki/w/Kroy)

One Efaritay's aid supplies 200 successful attacks against relevant targets. The cost calculation
uses the probability of a successful attack and the replacement price. Remaining charges on an
owned ring are unknown. Blisterwood stakes use the thrown weapon's ammunition recovery rules.
Missing prices leave the corresponding GP rate unavailable. For hypothetical quest-crafted gear,
an in-progress quest establishes a possible acquisition route. Materials and exact mid-quest
progress still need checking. Each observed physical item keeps its own identity.
[Efaritay's aid](https://oldschool.runescape.wiki/w/Efaritay%27s_aid) ·
[Blisterwood stakes](https://oldschool.runescape.wiki/w/Blisterwood_stake)

## Elite Void ranged

The Void ranger helm, Elite Void top, Elite Void robe and Void knight gloves together grant
10% effective ranged accuracy and 12.5% effective ranged strength on ordinary ranged attacks.
The optimizer considers the complete set even when individual pieces would lose on raw stats.
The published Sentinel loadouts give maximum hits of 26 and 28 with blisterwood stakes and 47
and 51 with a Hallowed flail, respectively without and with Efaritay's aid. These numbers apply
to the reference gear, levels and prayers.
[Elite Void](https://oldschool.runescape.wiki/w/Elite_Void_Knight_equipment) ·
[Sentinel reference loadouts](https://github.com/weirdgloop/osrs-dps-calc/blob/3da927f4280c73154fa59e4e90eb374af5123d32/src/tests/calc/Vampyre.test.ts)
