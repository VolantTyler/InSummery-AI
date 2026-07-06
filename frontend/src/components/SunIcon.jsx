import { useId } from "react";

export default function SunIcon({ className = "", size = 40, title = "InSummery" }) {
    const gradientId = useId();

    return (
        <svg
            className={className}
            width={size}
            height={size}
            viewBox="0 0 100 100"
            role="img"
            aria-label={title}
        >
            <defs>
                <radialGradient id={gradientId} cx="42%" cy="38%" r="55%">
                    <stop offset="0%" stopColor="#FFF176" />
                    <stop offset="55%" stopColor="#FFD600" />
                    <stop offset="100%" stopColor="#FFB300" />
                </radialGradient>
            </defs>
            <rect width="100" height="100" rx="18" fill="#C8E6FF" />
            <g transform="translate(50 50)">
                <g fill="#FFC107">
                    <polygon points="0,-44 8,-15 -8,-15" />
                    <polygon points="44,0 15,8 15,-8" />
                    <polygon points="0,44 -8,15 8,15" />
                    <polygon points="-44,0 -15,-8 -15,8" />
                </g>
                <g fill="#FFD54F">
                    <polygon points="31,-31 20,-13 13,-20" />
                    <polygon points="31,31 13,20 20,13" />
                    <polygon points="-31,31 -20,13 -13,20" />
                    <polygon points="-31,-31 -13,-20 -20,-13" />
                </g>
                <circle r="17" fill={`url(#${gradientId})`} />
                <circle r="17" fill="none" stroke="#FF8F00" strokeWidth="1.2" opacity="0.35" />
            </g>
        </svg>
    );
}
