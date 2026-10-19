/*
 * Copyright (c) 2019, Jos <Malevolentdev@gmail.com>
 * Copyright (c) 2019, Rheon <https://github.com/Rheon-D>
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice, this
 *    list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright notice,
 *    this list of conditions and the following disclaimer in the documentation
 *    and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
 * ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 * (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 * LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 * SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */
package com.osrstracker.plugin.statusbars;

import com.osrstracker.plugin.TrackerConfig;
import java.awt.Color;
import java.awt.Dimension;
import java.awt.Graphics2D;
import java.awt.Image;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.OptionalInt;
import javax.inject.Inject;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.Point;
import net.runelite.api.Prayer;
import net.runelite.api.Skill;
import net.runelite.api.gameval.SpriteID;
import net.runelite.api.gameval.VarPlayerID;
import net.runelite.api.gameval.VarbitID;
import net.runelite.api.widgets.Widget;
import net.runelite.client.game.AlternateSprites;
import net.runelite.client.game.SkillIconManager;
import net.runelite.client.game.SpriteManager;
import net.runelite.client.ui.overlay.Overlay;
import net.runelite.client.ui.overlay.OverlayLayer;
import net.runelite.client.ui.overlay.OverlayPosition;
import net.runelite.client.util.ImageUtil;

/** Backend-independent HP and Prayer bars anchored like RuneLite Status Bars. */
public final class EnhancedStatusBarsOverlay extends Overlay
{
    private final Client client;
    private final TrackerConfig config;
    private final EffectiveMaxHealthResolver resolver;
    private final SkillIconManager skillIcons;
    private final SpriteManager sprites;
    private final StatusBarRenderer renderer = new StatusBarRenderer();
    private final Image diseaseHeart = ImageUtil.loadImageResource(AlternateSprites.class, AlternateSprites.DISEASE_HEART);
    private final Image poisonHeart = ImageUtil.loadImageResource(AlternateSprites.class, AlternateSprites.POISON_HEART);
    private final Image venomHeart = ImageUtil.loadImageResource(AlternateSprites.class, AlternateSprites.VENOM_HEART);
    private volatile boolean suppressed;

    @Inject
    public EnhancedStatusBarsOverlay(Client client, TrackerConfig config,
        EffectiveMaxHealthResolver resolver, SkillIconManager skillIcons, SpriteManager sprites)
    {
        this.client = client;
        this.config = config;
        this.resolver = resolver;
        this.skillIcons = skillIcons;
        this.sprites = sprites;
        setPosition(OverlayPosition.DYNAMIC);
        setLayer(OverlayLayer.ABOVE_WIDGETS);
    }

    public void setSuppressed(boolean suppressed) { this.suppressed = suppressed; }

    @Override public Dimension render(Graphics2D graphics)
    {
        if (suppressed || !config.enhancedBarsEnabled() || client.getGameState() != GameState.LOGGED_IN
            || client.getLocalPlayer() == null)
        {
            return null;
        }
        for (StatusBarsViewport viewport : StatusBarsViewport.values())
        {
            Widget widget = client.getWidget(viewport.getViewport());
            if (widget != null && !widget.isHidden())
            {
                renderAtWidget(graphics, viewport, widget);
                break;
            }
        }
        return null;
    }

    private void renderAtWidget(Graphics2D g, StatusBarsViewport viewport, Widget widget)
    {
        Point location = widget.getCanvasLocation();
        if (location == null) { return; }
        boolean modern = viewport == StatusBarsViewport.RESIZED_BOTTOM;
        int height = modern ? 272 : 252;
        Point left = viewport.getOffsetLeft();
        Point right = viewport.getOffsetRight();
        int leftX = location.getX() - left.getX() + (modern ? 10 : 0);
        int leftY = location.getY() - left.getY() - (modern ? 12 : 0);
        int rightX = location.getX() - right.getX() + (modern ? 10 : widget.getWidth());
        int rightY = location.getY() - right.getY() - (modern ? 12 : 0);
        HealthResolution health = resolver.resolve();
        if (health.isAvailable())
        {
            renderer.render(g, leftX, leftY, StatusBarRenderer.WIDTH, height,
                health.maximum(), health.current(), healthColor(),
                config.statusBarsIcons() ? healthIcon() : null,
                config.statusBarsCounters(), config.statusBarsIcons(),
                markers(health.maximum(), leftY + 1, height - 2));
        }
        int prayerMax = resolver.isInLms() ? 99 : client.getRealSkillLevel(Skill.PRAYER);
        int prayerCurrent = client.getBoostedSkillLevel(Skill.PRAYER);
        if (prayerCurrent >= 0)
        {
            renderer.render(g, rightX, rightY, StatusBarRenderer.WIDTH, height,
                prayerMax, prayerCurrent, prayerColor(),
                config.statusBarsIcons() ? skillIcons.getSkillImage(Skill.PRAYER, true) : null,
                config.statusBarsCounters(), config.statusBarsIcons(), Collections.emptyList());
        }
    }

    private List<StatusBarRenderer.Marker> markers(int maximum, int top, int height)
    {
        if (!config.eatingThresholdsEnabled()) { return Collections.emptyList(); }
        List<StatusBarRenderer.Marker> markers = new ArrayList<>();
        addMarker(markers, config.sharkThresholdEnabled(), maximum, config.sharkHealing(), top,
            height, config.sharkMarkerColor());
        addMarker(markers, config.doubleEatThresholdEnabled(), maximum, config.doubleEatHealing(), top,
            height, config.doubleEatMarkerColor());
        addMarker(markers, config.tripleEatThresholdEnabled(), maximum, config.tripleEatHealing(), top,
            height, config.tripleEatMarkerColor());
        return Collections.unmodifiableList(markers);
    }

    private void addMarker(List<StatusBarRenderer.Marker> markers, boolean enabled, int maximum,
        int healing, int top, int height, Color color)
    {
        if (!enabled || color == null) { return; }
        OptionalInt position = EatingThresholds.calculate(maximum, healing, top, height);
        if (position.isPresent()) { markers.add(new StatusBarRenderer.Marker(position.getAsInt(), color)); }
    }

    private Color healthColor()
    {
        int poison = client.getVarpValue(VarPlayerID.POISON);
        if (poison >= 1000000) { return new Color(0, 65, 0, 150); }
        if (poison > 0) { return new Color(0, 145, 0, 150); }
        if (client.getVarpValue(VarPlayerID.DISEASE) > 0) { return new Color(255, 193, 75, 181); }
        if (client.getVarbitValue(VarbitID.PARASITE) >= 1) { return new Color(196, 62, 109, 181); }
        return new Color(225, 35, 0, 125);
    }

    private Image healthIcon()
    {
        int poison = client.getVarpValue(VarPlayerID.POISON);
        if (poison > 0 && poison < 50) { return poisonHeart; }
        if (poison >= 1000000) { return venomHeart; }
        if (client.getVarpValue(VarPlayerID.DISEASE) > 0) { return diseaseHeart; }
        return sprites.getSprite(SpriteID.OrbIcon.HITPOINTS, 0);
    }

    private Color prayerColor()
    {
        for (Prayer prayer : Prayer.values())
        {
            if (client.isPrayerActive(prayer)) { return new Color(57, 255, 186, 225); }
        }
        return new Color(50, 200, 200, 175);
    }
}
