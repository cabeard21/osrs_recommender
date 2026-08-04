# Official Hiscores — contingency only, not built for v1

See SDD §7.3 and §19.

Wise Old Man (`tracker/integrations/wise_old_man/`) is the primary remote source for
skills, boss KC, LMS score and XP history (§7.2). It already polls the official
hiscores, stores history and exposes gains, which is what lets one integration cover
both the "official hiscores" and "XP history" roles the original design split in two.

Direct hiscores access is retained only as a **documented fallback** for if WOM proves
unreliable — rate-limited, down for an extended period, or otherwise unfit as the
primary source. It is explicitly out of scope for v1 and no code exists here.

If this is ever implemented:

- Use the `index_lite.json` endpoint (`https://secure.runescape.com/m=hiscore_oldschool/index_lite.json?player=<name>`),
  not the HTML hiscores pages.
- **Normalize `-1` to `NULL`/`None` at the adapter boundary — never store or treat it
  as zero** (§6.2, G5). This is the same rule §7.2/§7.3 impose on Wise Old Man, since
  WOM itself sources from the hiscores and inherits the `-1` "unranked" sentinel.
- Source precedence remains `runelite > wise_old_man > hiscores` (§7.4) — a hiscores
  read must never be allowed to roll back a fresher RuneLite or WOM observation.
- This would live in `tracker/integrations/hiscores/client.py`, following the same
  shape as `tracker/integrations/wise_old_man/client.py`: a DTO-returning client with
  no writes of its own, using the shared retry/circuit-breaker transport in
  `tracker/integrations/http.py`.

Trigger for reopening this: Wise Old Man is unavailable or unreliable enough, in
practice, that skills/KC/LMS data cannot be sourced through it (§19).
