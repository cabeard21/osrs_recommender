package com.osrstracker.plugin.statusbars;

/** A fresh, immutable HP reading. Current HP is never repurposed as a maximum. */
public final class HealthResolution
{
    public enum Source { ACCOUNT, LMS, PETE_K, MANUAL, UNAVAILABLE }
    private final int current;
    private final int maximum;
    private final Source source;

    HealthResolution(int current, int maximum, Source source)
    {
        this.current = current;
        this.maximum = maximum;
        this.source = source;
    }

    public int current() { return current; }
    public int maximum() { return maximum; }
    public Source source() { return source; }
    public boolean isAvailable() { return maximum > 0 && current >= 0; }
    public double fillRatio()
    {
        return isAvailable() ? Math.min(1.0, (double) current / maximum) : 0.0;
    }
}
