package com.osrstracker.plugin.statusbars;

import java.util.List;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.NPC;
import net.runelite.api.Player;
import net.runelite.api.WorldView;
import net.runelite.api.coords.LocalPoint;
import net.runelite.api.coords.WorldPoint;

/**
 * Narrow Penultimate/Ultimate identification using public RuneLite 1.13.1 APIs.
 * Arena/form IDs are documented by Matsyir's PvP Performance Tracker at commit
 * 3e8c5bac7f3c6357fe6b9ca79428f2f954465ec7, utils/PeteKayer.java and its tests.
 * This is independently implemented; no combat analytics or equipment logic is imported.
 * Player maximum 99 is the user's confirmed rule for these two fights, not Pete's NPC stats.
 */
public final class PeteFightDetector
{
    private static final int ARENA_REGION = 11100;
    private PeteFightDetector() { }

    public static boolean isFight(Client client)
    {
        if (client.getGameState() != GameState.LOGGED_IN) return false;
        WorldPoint location = location(client);
        if (!isArena(location)) return false;
        List<NPC> npcs = client.getNpcs();
        if (npcs == null) return false;
        // Presence, not interaction: standing under Pete or pausing attacks does not end scaling.
        return npcs.stream().anyMatch(npc -> npc != null && isCombatForm(npc.getId()));
    }

    static WorldPoint location(Client client)
    {
        if (client.getGameState() != GameState.LOGGED_IN) return null;
        Player player = client.getLocalPlayer();
        if (player == null) return null;
        LocalPoint point = player.getLocalLocation();
        if (point == null) return null;
        WorldView view = client.getWorldView(point.getWorldView());
        if (view == null || (view.isInstance() && view.getInstanceTemplateChunks() == null)) return null;
        if (!view.isInstance() && client.getTopLevelWorldView() == null) return null;
        return WorldPoint.fromLocalInstance(client, point);
    }

    static boolean matches(WorldPoint location, int npcId)
    {
        return isArena(location) && isCombatForm(npcId);
    }

    private static boolean isArena(WorldPoint location)
    {
        return location != null && location.getRegionID() == ARENA_REGION && location.getPlane() == 0;
    }

    private static boolean isCombatForm(int id)
    {
        return (id >= 16579 && id <= 16586) || (id >= 16588 && id <= 16597);
    }
}
