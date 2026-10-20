// The platform's mark: a tape of events, the middle one cut short and
// checked. Inline so it takes a colour.
export default function Mark({ colour = "currentColor", size = 24 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true" style={{ flexShrink: 0 }}>
      <path d="M5 9h22M5 16h13M5 23h22" stroke={colour} strokeWidth="3" strokeLinecap="round" />
      <circle cx="24" cy="16" r="2.8" fill="#3FB68B" />
    </svg>
  );
}
