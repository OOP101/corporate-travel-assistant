import { useState } from 'react';

export interface TabProps {
  tabs: Array<{ label: string; value: string }>;
  defaultActive?: string;
  onChange: (value: string) => void;
  className?: string;
}

export const Tab = ({
  tabs,
  defaultActive = tabs[0]?.value,
  onChange,
  className,
}: TabProps) => {
  const [activeTab, setActiveTab] = useState(defaultActive);

  return (
    <div className={`inline-flex items-center gap-1 bg-gray-100/80 rounded-xl p-1 ${className || ''}`}>
      {tabs.map((tab) => {
        const active = activeTab === tab.value;
        return (
          <button
            key={tab.value}
            type="button"
            onClick={() => {
              setActiveTab(tab.value);
              onChange(tab.value);
            }}
            className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-all ${
              active
                ? 'bg-white text-primary-600 shadow-sm'
                : 'text-ink-600 hover:text-ink-900'
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
};
