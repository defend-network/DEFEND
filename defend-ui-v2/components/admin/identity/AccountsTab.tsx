import type { AccountSummary } from "@/lib/identityApi";

type AccountsTabProps = {
  accounts: AccountSummary[];
  onSelect?: (account: AccountSummary) => void;
};

function displayDate(value: string | null): string {
  if (!value) return "â€”";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function AccountsTab({ accounts, onSelect }: AccountsTabProps) {
  return (
    <div className="identity-table-scroll">
      <table aria-label="Accounts" className="identity-table">
        <thead>
          <tr>
            <th scope="col">Account</th>
            <th scope="col">Role</th>
            <th scope="col">Status</th>
            <th scope="col">Created</th>
            <th scope="col">Last access</th>
            <th scope="col">Recent IP</th>
            <th scope="col">Devices</th>
            <th scope="col">Sessions</th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((account) => (
            <tr key={account.account_id}>
              <td>
                <button
                  type="button"
                  className="identity-row-link"
                  onClick={() => onSelect?.(account)}
                >
                  <strong>{account.display_name}</strong>
                  <span>{account.email}</span>
                </button>
              </td>
              <td>{account.role}</td>
              <td>{account.status}</td>
              <td>{displayDate(account.created_at)}</td>
              <td>{displayDate(account.last_access_at)}</td>
              <td>{account.recent_ip ?? "â€”"}</td>
              <td>{account.device_count}</td>
              <td>{account.active_session_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
