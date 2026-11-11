// Brand mark: ascending contribution bars with an insight spark.
// public/favicon.svg and the PNG favicons mirror this geometry — keep them in sync.
export function LogoMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" focusable="false">
      <rect x="1.5" y="1.5" width="29" height="29" rx="8" fill="#0F172A" stroke="#1E293B" />
      <rect x="6.8" y="17.5" width="4" height="7" rx="1.2" fill="#10B981" opacity="0.45" />
      <rect x="11.6" y="13.5" width="4" height="11" rx="1.2" fill="#10B981" opacity="0.7" />
      <rect x="16.4" y="9.5" width="4" height="15" rx="1.2" fill="#10B981" />
      <rect x="21.2" y="5.5" width="4" height="19" rx="1.2" fill="#34D399" />
      <circle cx="23.2" cy="3.4" r="1.7" fill="#A7F3D0" />
    </svg>
  );
}
