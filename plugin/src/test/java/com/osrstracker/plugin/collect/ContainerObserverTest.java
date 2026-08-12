package com.osrstracker.plugin.collect;

import com.osrstracker.plugin.AccountSnapshot;
import net.runelite.api.Item;
import net.runelite.api.ItemContainer;
import net.runelite.api.Node;
import net.runelite.api.gameval.InventoryID;
import org.junit.Test;

import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * §6.5's ownership trichotomy, which is the design's most load-bearing distinction and the one
 * the reconciliation showed is easiest to break.
 */
public class ContainerObserverTest
{
	private static final Instant BANK_EVENT = Instant.parse("2026-08-12T10:00:00Z");
	private static final Instant BANK_CLOSED = Instant.parse("2026-08-12T10:00:30Z");
	private static final Instant INVENTORY_EVENT = Instant.parse("2026-08-12T10:01:00Z");

	private final ContainerObserver observer = new ContainerObserver();

	private static ItemContainer containerOf(Item... items)
	{
		// A hand-written double: ItemContainer is a small interface, and only getItems() is read.
		return new ItemContainer()
		{
			@Override
			public int getId()
			{
				return 0;
			}

			@Override
			public Item[] getItems()
			{
				return items;
			}

			@Override
			public Item getItem(int slot)
			{
				return items[slot];
			}

			@Override
			public boolean contains(int itemId)
			{
				for (Item item : items)
				{
					if (item.getId() == itemId)
					{
						return true;
					}
				}
				return false;
			}

			@Override
			public int count(int itemId)
			{
				return 0;
			}

			@Override
			public int size()
			{
				return items.length;
			}

			@Override
			public int count()
			{
				return items.length;
			}

			@Override
			public int find(int itemId)
			{
				return -1;
			}

			@Override
			public Node getNext()
			{
				return null;
			}

			@Override
			public Node getPrevious()
			{
				return null;
			}

			@Override
			public long getHash()
			{
				return 0;
			}
		};
	}

	private List<String> scannedContainers()
	{
		return observer.scans().stream()
			.map(scan -> scan.toJson().get("container").getAsString())
			.collect(Collectors.toList());
	}

	@Test
	public void aContainerNobodyLookedAtEmitsNoScan()
	{
		// The whole point. No scan means the app reads `unknown`; a scan here would mean
		// "observed, owns nothing" — D8's bug one layer out.
		assertTrue(observer.scans().isEmpty());
		assertTrue(observer.items().isEmpty());
	}

	@Test
	public void anEmptyBankStillEmitsAScan()
	{
		// Step 12b's exit criterion. The bank fired no change event — an empty container does not
		// — but the player opened and closed it, so the whole bank was seen.
		observer.onBankClosed(BANK_CLOSED);

		assertEquals(Collections.singletonList("bank"), scannedContainers());
		assertTrue(observer.items().isEmpty());
	}

	@Test
	public void aBankScanIsStampedWhenTheBankWasSeen()
	{
		observer.onContainerChanged(InventoryID.BANK, containerOf(new Item(995, 1000)), BANK_EVENT);
		observer.onBankClosed(BANK_CLOSED);

		// §4.5: the later sighting wins, and neither is "now".
		assertEquals("2026-08-12T10:00:30Z",
			observer.scans().get(0).toJson().get("scanned_at").getAsString());
	}

	@Test
	public void anObservedEmptyInventoryEmitsAScanWithNoItems()
	{
		// The capture that proved this: withdrawing an item and equipping it left the inventory
		// empty, and the event still fired. "Looked, found nothing" is representable.
		observer.onContainerChanged(InventoryID.INV, containerOf(), INVENTORY_EVENT);

		assertEquals(Collections.singletonList("inventory"), scannedContainers());
		assertTrue(observer.items().isEmpty());
	}

	@Test
	public void placeholdersAndEmptySlotsAreDropped()
	{
		// The schema requires quantity >= 1; a bank placeholder is quantity 0 and an empty slot
		// is id -1.
		observer.onContainerChanged(InventoryID.BANK,
			containerOf(new Item(995, 1000), new Item(4151, 0), new Item(-1, 5)), BANK_EVENT);

		final List<AccountSnapshot.ObservedItem> items = observer.items();
		assertEquals(1, items.size());
		assertEquals(995, items.get(0).toJson().get("item_id").getAsInt());
		assertEquals(1000, items.get(0).toJson().get("quantity").getAsInt());
	}

	@Test
	public void duplicateStacksAreSummed()
	{
		observer.onContainerChanged(InventoryID.INV,
			containerOf(new Item(560, 500), new Item(560, 250)), INVENTORY_EVENT);

		final List<AccountSnapshot.ObservedItem> items = observer.items();
		assertEquals(1, items.size());
		assertEquals(750, items.get(0).toJson().get("quantity").getAsInt());
	}

	@Test
	public void aContainerTheContractHasNoNameForIsIgnored()
	{
		// Trade screens, looting bags, deposit boxes. Collecting what has no sink would break the
		// §7.1 "nothing without a sink" rule and widen the payload past its schema.
		observer.onContainerChanged(99999, containerOf(new Item(995, 1)), INVENTORY_EVENT);

		assertTrue(observer.scans().isEmpty());
		assertTrue(observer.items().isEmpty());
	}

	@Test
	public void loggingOutForgetsWhatWasSeen()
	{
		observer.onContainerChanged(InventoryID.BANK, containerOf(new Item(995, 1)), BANK_EVENT);
		observer.onBankClosed(BANK_CLOSED);

		observer.reset();

		// Another account is about to log in; its bank has not been looked at.
		assertTrue(observer.scans().isEmpty());
		assertTrue(observer.items().isEmpty());
	}

	@Test
	public void eachObservedContainerIsScannedExactlyOnce()
	{
		observer.onContainerChanged(InventoryID.INV, containerOf(new Item(995, 1)), INVENTORY_EVENT);
		observer.onContainerChanged(InventoryID.INV, containerOf(new Item(995, 2)), INVENTORY_EVENT);

		assertEquals(1, observer.scans().size());
		// The later observation replaces the earlier one rather than accumulating.
		assertEquals(2, observer.items().get(0).toJson().get("quantity").getAsInt());
	}
}
