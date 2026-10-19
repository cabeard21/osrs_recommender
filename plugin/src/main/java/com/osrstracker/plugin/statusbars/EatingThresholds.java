package com.osrstracker.plugin.statusbars;

import java.util.OptionalInt;

/** Full nominal-heal efficiency thresholds, never combat eating recommendations. */
public final class EatingThresholds
{
    private EatingThresholds() { }

    public static OptionalInt thresholdHp(int maximum, int healing)
    {
        if (maximum <= 0 || healing <= 0 || healing > 255 || healing >= maximum)
            return OptionalInt.empty();
        return OptionalInt.of(maximum - healing);
    }

    public static OptionalInt calculate(int maximum, int healing, int top, int height)
    {
        if (height <= 0 || !thresholdHp(maximum, healing).isPresent()) return OptionalInt.empty();
        return OptionalInt.of(top + (int) Math.round((double) height * healing / maximum));
    }
}
