import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';

interface SettingsTabButtonProps {
  icon: LucideIcon;
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  badge?: string | number;
}

export function SettingsTabButton({ icon: Icon, active, onClick, children, badge }: SettingsTabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors w-full whitespace-nowrap',
        active ? 'bg-blue-50 text-blue-600' : 'text-gray-600 hover:bg-gray-100',
      ].join(' ')}
    >
      <Icon className="w-5 h-5" aria-hidden="true" />
      <span className="flex-1 text-left">{children}</span>
      {badge !== undefined ? (
        <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-gray-200 px-2 text-xs">
          {badge}
        </span>
      ) : null}
    </button>
  );
}

export default SettingsTabButton;
