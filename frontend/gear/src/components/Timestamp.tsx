const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];
const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function relativeTime(value: string, now = Date.now()): string | null {
  const time = Date.parse(value);
  if (Number.isNaN(time)) return null;
  const seconds = Math.round((time - now) / 1000);
  for (const [unit, size] of UNITS)
    if (Math.abs(seconds) >= size)
      return relative.format(Math.trunc(seconds / size), unit);
  return "just now";
}

export function Timestamp({ value }: { value: string }) {
  return (
    <time dateTime={value} title={value}>
      {relativeTime(value) ?? value}
    </time>
  );
}
