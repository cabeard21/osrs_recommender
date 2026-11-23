import { formatKg, type CarriedWeight } from "../api/carriedWeight";

export function RoleWeightBreakdown({
  weight,
  roleName,
}: {
  weight: CarriedWeight;
  roleName: (id: string) => string;
}) {
  const entries = Object.entries(weight.roles);
  if (entries.length < 2) return null;
  return (
    <details>
      <summary>Carried weight by role</summary>
      <table aria-label="Carried weight by role">
        <thead>
          <tr>
            <th scope="col">Role</th>
            <th scope="col">Worn</th>
            <th scope="col">Backpack</th>
            <th scope="col">Total</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([id, row]) => (
            <tr key={id}>
              <th scope="row">
                {roleName(id)}
                {row.total_kg === weight.heaviest_kg ? " · Heaviest" : ""}
              </th>
              <td>{formatKg(row.worn_kg)}</td>
              <td>{formatKg(row.backpack_kg)}</td>
              <td>{formatKg(row.total_kg)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
