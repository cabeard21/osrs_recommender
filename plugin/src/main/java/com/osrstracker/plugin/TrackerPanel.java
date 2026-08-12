package com.osrstracker.plugin;

import net.runelite.client.ui.ColorScheme;
import net.runelite.client.ui.PluginPanel;

import javax.swing.BorderFactory;
import javax.swing.BoxLayout;
import javax.swing.JButton;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.SwingUtilities;
import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Component;
import java.awt.Dimension;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

/**
 * The sidebar panel. Its whole job is the second half of step 12a task 3: <b>surface failures,
 * never silently</b>.
 *
 * <p>A sync that fails quietly is worse than one that never runs — the app keeps serving
 * yesterday's facts while looking current, which is the §15 honesty rule broken one layer
 * upstream of where §15 can see it.
 */
final class TrackerPanel extends PluginPanel
{
	private static final DateTimeFormatter TIME =
		DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneId.systemDefault());

	private final JLabel stateLabel = new JLabel();
	private final JLabel detailLabel = new JLabel();
	private final JLabel timeLabel = new JLabel();

	TrackerPanel(Runnable onSyncNow)
	{
		setLayout(new BorderLayout(0, 8));
		setBorder(BorderFactory.createEmptyBorder(10, 10, 10, 10));

		final JPanel status = new JPanel();
		status.setLayout(new BoxLayout(status, BoxLayout.Y_AXIS));
		status.setBackground(ColorScheme.DARK_GRAY_COLOR);

		final JLabel title = new JLabel("OSRS Tracker");
		title.setForeground(Color.WHITE);
		title.setAlignmentX(Component.LEFT_ALIGNMENT);
		stateLabel.setAlignmentX(Component.LEFT_ALIGNMENT);
		detailLabel.setAlignmentX(Component.LEFT_ALIGNMENT);
		timeLabel.setAlignmentX(Component.LEFT_ALIGNMENT);
		timeLabel.setForeground(ColorScheme.LIGHT_GRAY_COLOR);

		status.add(title);
		status.add(stateLabel);
		status.add(detailLabel);
		status.add(timeLabel);

		final JButton syncNow = new JButton("Sync now");
		syncNow.addActionListener(event -> onSyncNow.run());
		syncNow.setPreferredSize(new Dimension(100, 26));

		add(status, BorderLayout.NORTH);
		add(syncNow, BorderLayout.SOUTH);

		render(SyncStatus.idle());
	}

	/** Safe to call from any thread — Swing work is marshalled onto the EDT. */
	void update(SyncStatus status)
	{
		SwingUtilities.invokeLater(() -> render(status));
	}

	private void render(SyncStatus status)
	{
		stateLabel.setText(label(status));
		stateLabel.setForeground(color(status));

		// The detail can be a server error body; wrapping keeps a long one readable rather than
		// letting it stretch the sidebar and hide its own tail.
		detailLabel.setText("<html><body style='width:150px'>" + escape(status.detail()) + "</body></html>");
		detailLabel.setForeground(ColorScheme.LIGHT_GRAY_COLOR);

		timeLabel.setText(status.at() == null ? "" : TIME.format(status.at()));
	}

	private static String label(SyncStatus status)
	{
		switch (status.state())
		{
			case OK:
				return "Synced";
			case SENDING:
				return "Syncing…";
			case REJECTED:
				return "Rejected";
			case UNREACHABLE:
				return "Unreachable";
			case NOT_CONFIGURED:
				return "Not configured";
			default:
				return "Idle";
		}
	}

	private static Color color(SyncStatus status)
	{
		if (status.isFailure())
		{
			return ColorScheme.PROGRESS_ERROR_COLOR;
		}
		return status.state() == SyncStatus.State.OK
			? ColorScheme.PROGRESS_COMPLETE_COLOR
			: Color.WHITE;
	}

	private static String escape(String text)
	{
		return text == null
			? ""
			: text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
	}
}
