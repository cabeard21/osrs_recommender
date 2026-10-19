package com.osrstracker.plugin.statusbars;

import com.osrstracker.plugin.TrackerConfig;
import javax.inject.Inject;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.Skill;
import net.runelite.api.gameval.InterfaceID;

/** Activity rules take precedence over manual fallback, then normal trained HP. No session cache. */
public final class EffectiveMaxHealthResolver
{
    private final Client client;
    private final TrackerConfig config;

    @Inject
    public EffectiveMaxHealthResolver(Client client, TrackerConfig config)
    {
        this.client = client;
        this.config = config;
    }

    public HealthResolution resolve()
    {
        if (client.getGameState() != GameState.LOGGED_IN || client.getLocalPlayer() == null)
            return unavailable(-1);
        boolean automatic = config.automaticHpScaling();
        boolean lms = automatic && isInLms();
        boolean pete = automatic && !lms && PeteFightDetector.isFight(client);
        return resolve(client.getBoostedSkillLevel(Skill.HITPOINTS),
            client.getRealSkillLevel(Skill.HITPOINTS), true, lms, pete, automatic,
            config.manualHpMaximumEnabled(), config.manualHpMaximum());
    }

    /** Same published widget signal as RuneLite 1.13.1 Status Bars. */
    public boolean isInLms()
    {
        return client.getWidget(InterfaceID.BrOverlay.CONTENT) != null;
    }

    static HealthResolution resolve(int current, int real, boolean available, boolean lms,
        boolean pete, boolean automatic, boolean manual, int override)
    {
        if (!available || current < 0) return unavailable(current);
        if (automatic && lms) return new HealthResolution(current, 99, HealthResolution.Source.LMS);
        if (automatic && pete) return new HealthResolution(current, 99, HealthResolution.Source.PETE_K);
        if (manual)
            return override >= 1 && override <= 255
                ? new HealthResolution(current, override, HealthResolution.Source.MANUAL)
                : unavailable(current);
        return real > 0 ? new HealthResolution(current, real, HealthResolution.Source.ACCOUNT)
            : unavailable(current);
    }

    private static HealthResolution unavailable(int current)
    {
        return new HealthResolution(current, 0, HealthResolution.Source.UNAVAILABLE);
    }
}
