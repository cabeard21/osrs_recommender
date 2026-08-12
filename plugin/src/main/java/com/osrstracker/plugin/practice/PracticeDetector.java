package com.osrstracker.plugin.practice;

import com.osrstracker.plugin.AccountSnapshot;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * §7.6's practice detector: pure policy, no RuneLite types.
 *
 * <p>Everything that decides <em>whether something counts</em> lives here so it can be tested
 * against the table and — more importantly — against the table's <b>rejections</b>. The plugin
 * adapter that turns client events into these calls holds no policy at all.
 *
 * <table>
 *   <caption>§7.6</caption>
 *   <tr><th>Signal</th><th>May refresh</th></tr>
 *   <tr><td>Entry into and exit from an LMS match</td><td>lms, nh_combat, general_pvp</td></tr>
 *   <tr><td>Sustained player combat in LMS</td><td>lms, nh_combat</td></tr>
 *   <tr><td>Sustained player combat in the Wilderness</td><td>wilderness_pvp, general_pvp</td></tr>
 *   <tr><td>Attacked in the Wilderness, <b>and fights back</b></td><td>anti_pking</td></tr>
 *   <tr><td>Merely entering the Wilderness</td><td><b>nothing</b></td></tr>
 *   <tr><td>Equipping multiple combat styles</td><td><b>nothing</b></td></tr>
 *   <tr><td>Switching prayers rapidly</td><td><b>nothing</b></td></tr>
 *   <tr><td>Logging in after a long break</td><td><b>nothing</b></td></tr>
 * </table>
 *
 * <p><b>The rejected signals have methods anyway.</b> They are deliberately inert, and that is
 * the point: a rejection expressed as a missing method is invisible, and the next author wires
 * the event up because nothing said not to. Expressed as a named no-op with a test, it is a
 * decision someone has to overrule on purpose.
 *
 * <p><b>G7 boundary.</b> Nothing here sets {@code achieved}. Practice evidence refreshes
 * <em>freshness</em> only — participation is never competence — and the four-field event shape
 * is all that leaves the plugin (G8).
 */
public final class PracticeDetector
{
	/** Where the player is. Nothing outside these two arenas can produce practice evidence. */
	public enum Arena
	{
		LMS,
		WILDERNESS,
		ELSEWHERE
	}

	// §7.6 domains, as the frozen contract spells them.
	static final String LMS = "lms";
	static final String NH_COMBAT = "nh_combat";
	static final String WILDERNESS_PVP = "wilderness_pvp";
	static final String ANTI_PKING = "anti_pking";
	static final String GENERAL_PVP = "general_pvp";

	// §6.7 evidence types. A closed enum on purpose: an open string is where
	// `opponent_dashboard_screenshot` eventually arrives.
	static final String LMS_MATCH_COMPLETED = "lms_match_completed";
	static final String LMS_PLAYER_COMBAT = "lms_player_combat";
	static final String WILDERNESS_PLAYER_COMBAT = "wilderness_player_combat";

	/**
	 * "Combat occurred" for v1: at least two player-directed attacks, or at least ten seconds in
	 * a player-combat state. Quoting the plan: <i>"This prevents a milestone refreshing because
	 * someone misclicked another player or took a single hit while escaping."</i>
	 */
	static final int MIN_ATTACKS = 2;
	static final Duration MIN_DURATION = Duration.ofSeconds(10);

	/** Quiet time that ends an engagement. Long enough to survive a re-approach mid-fight. */
	static final Duration SESSION_GAP = Duration.ofSeconds(30);

	private Session session;
	private Instant lmsMatchStartedAt;
	private final List<AccountSnapshot.PracticeEvent> pending = new ArrayList<>();

	/** One contiguous engagement. */
	private static final class Session
	{
		private final Arena arena;
		private final Instant startedAt;
		private Instant lastActivityAt;
		private int attacks;
		private boolean weWereAttackedFirst;
		private boolean weFoughtBack;

		private Session(Arena arena, Instant at)
		{
			this.arena = arena;
			this.startedAt = at;
			this.lastActivityAt = at;
		}

		private boolean qualifies()
		{
			return attacks >= MIN_ATTACKS
				|| !Duration.between(startedAt, lastActivityAt).minus(MIN_DURATION).isNegative();
		}
	}

	// ---------------------------------------------------------------------------------------
	// Signals that count
	// ---------------------------------------------------------------------------------------

	/**
	 * One player-directed attack, in either direction.
	 *
	 * @param weAttacked      the local player attacked another player
	 * @param weWereAttacked  another player attacked the local player
	 */
	public void observePlayerCombat(Arena arena, Instant at, boolean weAttacked, boolean weWereAttacked)
	{
		if (arena == Arena.ELSEWHERE || (!weAttacked && !weWereAttacked))
		{
			return;
		}

		if (session != null && (session.arena != arena || isStale(at)))
		{
			closeSession();
		}
		if (session == null)
		{
			session = new Session(arena, at);
			// Being hit before landing one is what distinguishes an anti-PK from a fight the
			// player picked. Recorded at the session's first observation, never revised.
			session.weWereAttackedFirst = weWereAttacked && !weAttacked;
		}

		session.lastActivityAt = at;
		session.attacks++;
		if (weAttacked)
		{
			session.weFoughtBack = true;
		}
	}

	/**
	 * The player is <em>in</em> a player-combat state right now — engaged with another player,
	 * without a new attack having landed this tick.
	 *
	 * <p>This is what makes the ten-second arm of the threshold reachable. Attacks alone cannot
	 * express it: with a single attack the session's start and end are the same instant, so a
	 * duration test over attack timestamps would always read zero and the arm would be dead code
	 * that looked alive.
	 */
	public void observeCombatState(Arena arena, Instant at)
	{
		if (arena == Arena.ELSEWHERE)
		{
			return;
		}
		if (session != null && (session.arena != arena || isStale(at)))
		{
			closeSession();
		}
		if (session == null)
		{
			session = new Session(arena, at);
		}
		session.lastActivityAt = at;
	}

	public void lmsMatchStarted(Instant at)
	{
		lmsMatchStartedAt = at;
	}

	/**
	 * A completed LMS match is evidence on its own — §7.6 credits entry <em>and</em> exit, not
	 * just the fighting in between.
	 */
	public void lmsMatchEnded(Instant at)
	{
		if (lmsMatchStartedAt == null)
		{
			// The client was started mid-match, or the varbit flickered. No start, no span, and
			// §4.5 forbids inventing one.
			return;
		}
		emit(LMS_MATCH_COMPLETED, lmsMatchStartedAt, at, LMS, NH_COMBAT, GENERAL_PVP);
		lmsMatchStartedAt = null;
		closeSession();
	}

	// ---------------------------------------------------------------------------------------
	// Signals §7.6 explicitly rejects. Inert by design — see the class note.
	// ---------------------------------------------------------------------------------------

	/** Being in the Wilderness is not practice. Standing in Edgeville is not a fight. */
	public void observeWildernessEntry(Instant at)
	{
	}

	/** Rapid prayer switching alone proves nothing — a player can flick at a training dummy. */
	public void observePrayerSwitch(Instant at)
	{
	}

	/** Equipping several combat styles is preparation, not execution. */
	public void observeStyleSwitch(Instant at)
	{
	}

	/** Logging in after a long break is the opposite of evidence. */
	public void observeLogin(Instant at)
	{
	}

	// ---------------------------------------------------------------------------------------

	/**
	 * Close any finished engagement and hand over what qualified.
	 *
	 * <p>Called when a snapshot is being built. Events are returned once and then forgotten —
	 * the server owns the history (§6.7), and re-sending would inflate a session into many.
	 */
	public List<AccountSnapshot.PracticeEvent> drain(Instant now)
	{
		if (session != null && isStale(now))
		{
			closeSession();
		}
		if (pending.isEmpty())
		{
			return Collections.emptyList();
		}
		final List<AccountSnapshot.PracticeEvent> drained = new ArrayList<>(pending);
		pending.clear();
		return drained;
	}

	/** Login/logout boundary: an unfinished engagement belongs to the account that fought it. */
	public void reset()
	{
		session = null;
		lmsMatchStartedAt = null;
		pending.clear();
	}

	private boolean isStale(Instant now)
	{
		return Duration.between(session.lastActivityAt, now).compareTo(SESSION_GAP) > 0;
	}

	private void closeSession()
	{
		final Session finished = session;
		session = null;
		if (finished == null || !finished.qualifies())
		{
			// One misclick, or a single hit taken while escaping. Not practice.
			return;
		}

		if (finished.arena == Arena.LMS)
		{
			emit(LMS_PLAYER_COMBAT, finished.startedAt, finished.lastActivityAt, LMS, NH_COMBAT);
			return;
		}

		emit(WILDERNESS_PLAYER_COMBAT, finished.startedAt, finished.lastActivityAt,
			WILDERNESS_PVP, GENERAL_PVP);

		if (finished.weWereAttackedFirst && finished.weFoughtBack)
		{
			// §7.6, medium confidence, and only with the fighting back: being killed on a PvM
			// setup teaches nothing, and crediting it would reward dying.
			emit(WILDERNESS_PLAYER_COMBAT, finished.startedAt, finished.lastActivityAt, ANTI_PKING);
		}
	}

	private void emit(String evidenceType, Instant startedAt, Instant endedAt, String... domains)
	{
		for (String domain : domains)
		{
			pending.add(new AccountSnapshot.PracticeEvent(domain, startedAt, endedAt, evidenceType));
		}
	}
}
