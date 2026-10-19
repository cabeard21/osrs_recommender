package com.osrstracker.plugin.statusbars;

import org.junit.Test;
import static org.junit.Assert.*;

public class HealthCalculationsTest
{
    private HealthResolution resolve(int hp, int real, boolean lms, boolean pete,
        boolean auto, boolean manual, int override)
    {
        return EffectiveMaxHealthResolver.resolve(hp, real, true, lms, pete, auto, manual, override);
    }

    @Test public void accountUsesRealMaximumAndActualCurrentValue()
    {
        assertEquals(1.0, resolve(54,54,false,false,true,false,99).fillRatio(),0);
        HealthResolution health = resolve(30,54,false,false,true,false,99);
        assertEquals(30,health.current());
        assertEquals(54,health.maximum());
        assertEquals(30.0/54,health.fillRatio(),0.00001);
        assertEquals(HealthResolution.Source.ACCOUNT,health.source());
    }

    @Test public void normalizedActivitiesTakePrecedenceOverManualMaximum()
    {
        HealthResolution lms = resolve(54,54,true,false,true,true,75);
        assertEquals(99,lms.maximum());
        assertEquals(54.0/99,lms.fillRatio(),0.00001);
        assertEquals(HealthResolution.Source.LMS,lms.source());
        HealthResolution pete = resolve(54,54,false,true,true,true,75);
        assertEquals(99,pete.maximum());
        assertEquals(HealthResolution.Source.PETE_K,pete.source());
        assertEquals(1.0,resolve(99,54,false,true,true,false,99).fillRatio(),0);
        assertEquals(1.0,resolve(99,54,true,false,true,false,99).fillRatio(),0);
    }

    @Test public void manualModeAndAutomaticDisabledUseExplicitPolicy()
    {
        assertEquals(99,resolve(54,54,false,false,true,true,99).maximum());
        assertEquals(HealthResolution.Source.MANUAL,resolve(54,54,true,true,false,true,99).source());
        assertEquals(75,resolve(54,54,true,true,false,true,75).maximum());
        assertEquals(54,resolve(54,54,true,true,false,false,99).maximum());
        assertEquals(1,resolve(0,54,false,false,true,true,1).maximum());
        assertEquals(255,resolve(54,54,false,false,true,true,255).maximum());
    }

    @Test public void activityExitRestoresAccountAndDoesNotCarryAcrossAccounts()
    {
        assertEquals(99,resolve(54,54,false,true,true,false,99).maximum());
        assertEquals(54,resolve(54,54,false,false,true,false,99).maximum());
        assertFalse(EffectiveMaxHealthResolver.resolve(54,54,false,true,true,true,true,99).isAvailable());
        assertEquals(80,resolve(80,80,false,false,true,false,99).maximum());
    }

    @Test public void unknownValuesDoNotBecomeFullHealth()
    {
        for (int value : new int[]{-1,0,256})
            assertFalse(resolve(54,54,false,false,true,true,value).isAvailable());
        assertFalse(resolve(54,0,false,false,true,false,99).isAvailable());
        assertFalse(resolve(-1,54,false,false,true,false,99).isAvailable());
        assertEquals(0,resolve(54,0,false,false,true,false,99).fillRatio(),0);
        assertEquals(HealthResolution.Source.UNAVAILABLE,resolve(54,0,false,false,true,false,99).source());
        assertTrue(resolve(54,0,true,false,true,false,99).isAvailable());
    }

    @Test public void overhealingClampsFillWithoutChangingCounter()
    {
        HealthResolution health = resolve(120,54,false,false,true,false,99);
        assertEquals(120,health.current());
        assertEquals(1,health.fillRatio(),0);
        assertEquals(0,resolve(0,54,false,false,true,false,99).fillRatio(),0);
    }

    @Test public void nominalHealingThresholdsAreMathematicallyCorrect()
    {
        int[] heals={20,35,56}; int[] thresholds={79,64,43};
        for (int i=0;i<heals.length;i++)
        {
            assertEquals(thresholds[i],EatingThresholds.thresholdHp(99,heals[i]).getAsInt());
            assertEquals(10+(int)Math.round(250.0*heals[i]/99),EatingThresholds.calculate(99,heals[i],10,250).getAsInt());
        }
        assertEquals(34,EatingThresholds.thresholdHp(54,20).getAsInt());
        assertEquals(19,EatingThresholds.thresholdHp(54,35).getAsInt());
        assertFalse(EatingThresholds.thresholdHp(54,56).isPresent());
    }

    @Test public void invalidAndOutOfRangeMarkersAreOmitted()
    {
        for(int max:new int[]{-1,0,54})
            for(int heal:new int[]{-1,0,54,56,256})
                assertFalse(EatingThresholds.calculate(max,heal,10,250).isPresent());
        assertFalse(EatingThresholds.calculate(99,20,10,0).isPresent());
        assertFalse(EatingThresholds.calculate(99,20,10,-1).isPresent());
    }

    @Test public void resizingAndMaximumChangesRecomputeCoordinates()
    {
        assertEquals(51,EatingThresholds.calculate(99,20,0,250).getAsInt());
        assertEquals(55,EatingThresholds.calculate(99,20,0,270).getAsInt());
        assertEquals(93,EatingThresholds.calculate(54,20,0,250).getAsInt());
    }
}
