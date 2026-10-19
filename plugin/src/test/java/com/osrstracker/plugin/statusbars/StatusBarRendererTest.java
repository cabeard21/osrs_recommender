package com.osrstracker.plugin.statusbars;

import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.util.Arrays;
import java.util.Collections;
import org.junit.Test;
import static org.junit.Assert.*;

public class StatusBarRendererTest
{
    @Test public void firstFrameUsesCurrentValuesAndSharedDrawableGeometry()
    {
        BufferedImage image = new BufferedImage(100, 300, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = image.createGraphics();
        StatusBarRenderer renderer = new StatusBarRenderer();
        renderer.render(g, 20, 10, 20, 252, 99, 54, Color.RED, null, false, false,
            Collections.emptyList());
        assertEquals(Color.RED.getRGB(), image.getRGB(25, 200));
        assertNotEquals(Color.RED.getRGB(), image.getRGB(25, 100));
        assertEquals(125, StatusBarRenderer.fillTop(99, 54, 11, 250));
        g.dispose();
    }

    @Test public void markersRenderOverFillAndCoincidentRowsKeepBothColors()
    {
        BufferedImage image = new BufferedImage(100, 300, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = image.createGraphics();
        new StatusBarRenderer().render(g, 20, 10, 20, 252, 99, 99, Color.RED, null,
            false, false, Arrays.asList(new StatusBarRenderer.Marker(50, Color.YELLOW),
                new StatusBarRenderer.Marker(50, Color.CYAN)));
        assertEquals(Color.YELLOW.getRGB(), image.getRGB(21, 50));
        assertEquals(Color.CYAN.getRGB(), image.getRGB(37, 50));
        assertEquals(Color.BLACK.getRGB(), image.getRGB(25, 49));
        g.dispose();
    }

    @Test public void clampsFillAndOmitsInvalidMaximum()
    {
        assertEquals(11, StatusBarRenderer.fillTop(99, 120, 11, 250));
        assertEquals(261, StatusBarRenderer.fillTop(99, -1, 11, 250));
        BufferedImage image = new BufferedImage(100, 300, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = image.createGraphics();
        new StatusBarRenderer().render(g, 20, 10, 20, 252, 0, 54, Color.RED, null,
            true, true, Collections.emptyList());
        assertEquals(0, image.getRGB(25, 200));
        g.dispose();
    }
    @Test public void foregroundAndSmallGeometryAreHandledSafely()
    {
        BufferedImage image = new BufferedImage(100, 300, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = image.createGraphics();
        BufferedImage icon = new BufferedImage(8, 8, BufferedImage.TYPE_INT_ARGB);
        Graphics2D ig = icon.createGraphics();
        ig.setColor(Color.BLUE); ig.fillRect(0,0,8,8); ig.dispose();
        StatusBarRenderer r = new StatusBarRenderer();
        r.render(g,20,10,20,252,99,120,Color.RED,icon,true,true,Collections.emptyList());
        assertEquals(Color.BLUE.getRGB(),image.getRGB(27,15));
        r.render(g,50,10,20,252,99,54,Color.RED,null,true,false,Collections.emptyList());
        r.render(g,75,10,10,252,99,54,Color.RED,icon,true,true,Collections.emptyList());
        assertNotEquals(Color.BLUE.getRGB(),image.getRGB(78,15));
        r.render(g,0,0,2,10,99,54,Color.RED,null,false,false,Collections.emptyList());
        r.render(g,0,0,20,2,99,54,Color.RED,null,false,false,Collections.emptyList());
        assertEquals(0,image.getRGB(0,0));
        assertEquals(11,StatusBarRenderer.fillTop(0,54,1,10));
        g.dispose();
    }
    @Test public void everyValidThresholdSharesExactlyTheFillBoundaryRounding()
    {
        for(int maximum=2;maximum<=255;maximum++)
            for(int healing=1;healing<maximum;healing++)
                for(int height:new int[]{250,270})
                    assertEquals("M="+maximum+" H="+healing+" height="+height,
                        EatingThresholds.calculate(maximum,healing,15,height).getAsInt(),
                        StatusBarRenderer.fillTop(maximum,maximum-healing,15,height));
    }

}
