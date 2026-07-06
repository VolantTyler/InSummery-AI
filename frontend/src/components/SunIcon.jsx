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
            <g transform="translate(50 50)">
                <g fill="#FFC107">
                    <polygon points="0,-38 7,-18 -7,-18" />
                    <polygon points="0,38 -7,18 7,18" />
                    <polygon points="-38,0 -18,-7 -18,7" />
                    <polygon points="38,0 18,7 18,-7" />
                </g>
                <g fill="#FFD54F">
                    <polygon points="27,-27 32,-14 20,-20" />
                    <polygon points="27,27 20,20 32,14" />
                    <polygon points="-27,27 -20,20 -32,14" />
                    <polygon points="-27,-27 -32,-14 -20,-20" />
                </g>
                <circle r="17" fill={`url(#${gradientId})`} />
                <circle r="17" fill="none" stroke="#FF8F00" strokeWidth="1.2" opacity="0.35" />
            </g>
        </svg>
    );
}
