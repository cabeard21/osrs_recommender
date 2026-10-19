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
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
 * SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
 * CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */
package com.osrstracker.plugin.statusbars;

import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.Point;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.ArrayList;
import net.runelite.client.ui.FontManager;
import net.runelite.client.ui.overlay.components.TextComponent;

/** Local adaptation of RuneLite Status Bars, without restoration previews. */
final class StatusBarRenderer
{
    static final int WIDTH = 20;
    private static final Color BACKGROUND = new Color(0, 0, 0, 150);

    static final class Marker
    {
        final int y;
        final Color color;
        Marker(int y, Color color) { this.y = y; this.color = color; }
    }

    static int fillTop(int maximum, int current, int top, int height)
    {
        if (maximum <= 0) { return top + height; }
        int missing = maximum - Math.max(0, Math.min(maximum, current));
        // Use the same arithmetic order as threshold coordinates; subtracting a floating
        // fill ratio can move an exact half-pixel boundary by one pixel.
        return top + (int) Math.round((double) height * missing / maximum);
    }

    void render(Graphics2D graphics, int x, int y, int width, int height, int maximum,
        int current, Color color, Image icon, boolean counters, boolean icons, List<Marker> markers)
    {
        if (maximum <= 0 || width < 3 || height < 3) { return; }
        int top = y + 1;
        int bottom = top + height - 2;
        int fillTop = fillTop(maximum, current, top, height - 2);
        graphics.setColor(BACKGROUND);
        graphics.fillRect(x, y, width, height);
        graphics.setColor(color);
        graphics.fillRect(x + 1, fillTop, width - 2, bottom - fillTop);
        renderMarkers(graphics, x, width, markers);
        renderForeground(graphics, x, y, width, current, icon, counters, icons);
    }

    private void renderMarkers(Graphics2D g, int x, int width, List<Marker> markers)
    {
        Map<Integer, List<Color>> rows = new TreeMap<>();
        for (Marker marker : markers)
        {
            rows.computeIfAbsent(marker.y, ignored -> new ArrayList<>()).add(marker.color);
        }
        for (Map.Entry<Integer, List<Color>> row : rows.entrySet())
        {
            int start = x - 2;
            int span = width + 4;
            int y = row.getKey();
            g.setColor(Color.BLACK);
            g.fillRect(start, y - 1, span, 3);
            List<Color> colors = row.getValue();
            for (int i = 0; i < colors.size(); i++)
            {
                int left = start + span * i / colors.size();
                int right = start + span * (i + 1) / colors.size();
                g.setColor(colors.get(i));
                g.drawLine(left, y, right - 1, y);
            }
        }
    }

    private void renderForeground(Graphics2D g, int x, int y, int width, int current,
        Image icon, boolean counters, boolean icons)
    {
        if (width < 16) { return; }
        if (icons && icon != null)
        {
            g.drawImage(icon, x + width / 2 - icon.getWidth(null) / 2, y + 4, null);
        }
        if (counters)
        {
            g.setFont(FontManager.getRunescapeSmallFont());
            String text = Integer.toString(current);
            TextComponent component = new TextComponent();
            component.setText(text);
            component.setPosition(new Point(x + (width - g.getFontMetrics().stringWidth(text)) / 2,
                y + (icons ? 35 : 18)));
            component.render(g);
        }
    }
}
