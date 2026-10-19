package com.osrstracker.plugin.statusbars;

import com.osrstracker.plugin.TrackerConfig;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.function.Consumer;
import java.util.stream.Collectors;
import javax.inject.Inject;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.NPC;
import net.runelite.api.Skill;
import net.runelite.api.coords.WorldPoint;
import net.runelite.api.widgets.Widget;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** Explicitly opted-in local snapshots; no continuous health log and no network dependency. */
public final class HpScalingDiagnostics
{
    private static final Logger LOG = LoggerFactory.getLogger(HpScalingDiagnostics.class);
    private final Client client;
    private final TrackerConfig config;
    private final EffectiveMaxHealthResolver resolver;
    private final Consumer<String> sink;
    private String lastSignature;

    @Inject
    public HpScalingDiagnostics(Client client, TrackerConfig config, EffectiveMaxHealthResolver resolver)
    {
        this(client,config,resolver,LOG::info);
    }

    HpScalingDiagnostics(Client client, TrackerConfig config, EffectiveMaxHealthResolver resolver,
        Consumer<String> sink)
    {
        this.client=client;
        this.config=config;
        this.resolver=resolver;
        this.sink=sink;
    }

    /** Invoked on the client thread by plugin lifecycle/configuration/game-state events. */
    public void tick()
    {
        if (!config.enhancedBarsEnabled() || !config.hpScalingDiagnostics())
        {
            reset();
            return;
        }
        HealthResolution health=resolver.resolve();
        WorldPoint location=location();
        String region=location==null ? "unknown" : location.getRegionID()+":"+location.getPlane();
        String signature=client.getGameState()+":"+health.source()+":"+health.maximum()+":"+region
            +":"+config.sharkHealing()+":"+config.doubleEatHealing()+":"+config.tripleEatHealing();
        if (signature.equals(lastSignature)) return;
        lastSignature=signature;
        sink.accept("HP scaling: state="+client.getGameState()+" source="+health.source()
            +" current="+health.current()+" real="+realHp()+" max="+health.maximum()
            +" region:plane="+region+" Pete forms="+peteForms(location)
            +" visible root interfaces="+visibleInterfaces()+" world types="+client.getWorldType()
            +" marker healing="+config.sharkHealing()+","+config.doubleEatHealing()+","+config.tripleEatHealing()
            +" (markers outside 0 < healing < max are omitted)");
    }

    public void reset() { lastSignature=null; }

    private int realHp()
    {
        return client.getGameState()==GameState.LOGGED_IN ? client.getRealSkillLevel(Skill.HITPOINTS) : -1;
    }

    private WorldPoint location()
    {
        return PeteFightDetector.location(client);
    }

    private List<Integer> peteForms(WorldPoint location)
    {
        if (location==null) return Collections.emptyList();
        List<NPC> npcs=client.getNpcs();
        if (npcs==null) return Collections.emptyList();
        return npcs.stream().filter(npc -> npc!=null && PeteFightDetector.matches(location,npc.getId()))
            .map(NPC::getId).distinct().collect(Collectors.toList());
    }

    private List<Integer> visibleInterfaces()
    {
        if (client.getGameState()!=GameState.LOGGED_IN) return Collections.emptyList();
        Widget[] roots=client.getWidgetRoots();
        if (roots==null) return Collections.emptyList();
        return Arrays.stream(roots).filter(widget -> widget!=null && !widget.isHidden())
            .map(widget -> widget.getId() >>> 16).distinct().collect(Collectors.toList());
    }
}
