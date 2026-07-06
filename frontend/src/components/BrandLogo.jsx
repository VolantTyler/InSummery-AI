import SunIcon from "./SunIcon.jsx";

export default function BrandLogo({ size = 40, showText = true, textClassName = "" }) {
    return (
        <div className="brand-logo">
            <SunIcon className="brand-logo-icon" size={size} />
            {showText && <span className={`brand-logo-text ${textClassName}`.trim()}>InSummery</span>}
        </div>
    );
}
