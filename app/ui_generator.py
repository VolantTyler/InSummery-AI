import os
from datetime import datetime, timedelta
from jinja2 import Template
from typing import Dict, Any, List

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Summify Schedule Matrix</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --text-color: #1e293b;
            --text-muted: #64748b;
            --border-color: #e2e8f0;
            --primary: #4f46e5;
            --primary-hover: #4338ca;
            --success-bg: #e6f4ea;
            --success-text: #137333;
            --danger-bg: #fce8e6;
            --danger-text: #c5221f;
            --warning-bg: #fef7e0;
            --warning-text: #b06000;
            --school-bg: #f1f5f9;
            --school-text: #475569;
        }

        [data-theme="dark"] {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-color: #f8fafc;
            --text-muted: #94a3b8;
            --border-color: #334155;
            --primary: #818cf8;
            --primary-hover: #6366f1;
            --success-bg: #0f5132;
            --success-text: #d1e7dd;
            --danger-bg: #842029;
            --danger-text: #f8d7da;
            --warning-bg: #664d03;
            --warning-text: #fff3cd;
            --school-bg: #334155;
            --school-text: #cbd5e1;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 0;
            transition: background-color 0.3s, color 0.3s;
            font-size: 18px;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 24px 40px;
            background-color: var(--card-bg);
            border-bottom: 1px solid var(--border-color);
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }

        h1 {
            margin: 0;
            font-size: 28px;
            font-weight: 700;
            color: var(--primary);
        }

        .theme-toggle {
            background: none;
            border: 1px solid var(--border-color);
            color: var(--text-color);
            padding: 10px 20px;
            border-radius: 9999px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.2s;
        }

        .theme-toggle:hover {
            background-color: var(--border-color);
        }

        .container {
            display: grid;
            grid-template-columns: 1fr 350px;
            gap: 40px;
            padding: 40px;
            max-width: 1400px;
            margin: 0 auto;
        }

        @media (max-width: 1024px) {
            .container {
                grid-template-columns: 1fr;
            }
        }

        .schedule-grid {
            display: flex;
            flex-direction: column;
            gap: 32px;
        }

        .day-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
        }

        .day-header {
            font-size: 22px;
            font-weight: 700;
            margin-bottom: 20px;
            border-bottom: 2px solid var(--primary);
            padding-bottom: 8px;
            color: var(--text-color);
        }

        .children-columns {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 24px;
        }

        .child-column {
            background-color: var(--bg-color);
            border-radius: 12px;
            padding: 16px;
            border: 1px dashed var(--border-color);
        }

        .child-name {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 16px;
            text-align: center;
            color: var(--primary);
        }

        .timeline-item {
            margin-bottom: 12px;
            padding: 14px;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 500;
            box-shadow: 0 1px 2px rgba(0,0,0,0.02);
            transition: transform 0.2s;
        }

        .timeline-item:hover {
            transform: translateY(-2px);
        }

        .item-time {
            font-size: 14px;
            font-weight: 700;
            margin-bottom: 4px;
            opacity: 0.8;
        }

        .item-title {
            font-size: 16px;
            font-weight: 600;
        }

        .item-notes {
            font-size: 14px;
            margin-top: 4px;
            opacity: 0.9;
            font-style: italic;
        }

        .status-active {
            background-color: var(--success-bg);
            color: var(--success-text);
            border-left: 4px solid var(--success-text);
        }

        .status-disrupted {
            background-color: var(--warning-bg);
            color: var(--warning-text);
            border-left: 4px solid var(--warning-text);
            text-decoration: line-through;
        }

        .status-gap {
            background-color: var(--danger-bg);
            color: var(--danger-text);
            border-left: 4px solid var(--danger-text);
            animation: pulse 2s infinite;
        }

        .status-school {
            background-color: var(--school-bg);
            color: var(--school-text);
            border-left: 4px solid var(--school-text);
        }

        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(197, 34, 31, 0.4); }
            70% { box-shadow: 0 0 0 6px rgba(197, 34, 31, 0); }
            100% { box-shadow: 0 0 0 0 rgba(197, 34, 31, 0); }
        }

        .sidebar {
            display: flex;
            flex-direction: column;
            gap: 24px;
        }

        .sidebar-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
        }

        .sidebar-title {
            font-size: 20px;
            font-weight: 700;
            margin-top: 0;
            margin-bottom: 16px;
            color: var(--primary);
        }

        .alert-item {
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 12px;
            font-size: 15px;
            border: 1px solid var(--border-color);
        }

        .alert-absolute {
            background-color: var(--danger-bg);
            color: var(--danger-text);
            border-left: 4px solid var(--danger-text);
        }

        .alert-relative {
            background-color: var(--warning-bg);
            color: var(--warning-text);
            border-left: 4px solid var(--warning-text);
        }

        .alert-disruption {
            background-color: var(--school-bg);
            color: var(--school-text);
            border-left: 4px solid var(--school-text);
        }

        .no-alerts {
            color: var(--text-muted);
            font-style: italic;
            font-size: 16px;
        }
    </style>
</head>
<body>
    <header>
        <h1>Summify Schedule Matrix</h1>
        <button class="theme-toggle" onclick="toggleTheme()">Toggle Dark Mode</button>
    </header>

    <div class="container">
        <div class="schedule-grid">
            {% for day in days %}
            <div class="day-card">
                <div class="day-header">{{ day.name }}</div>
                <div class="children-columns">
                    {% for child in day.children %}
                    <div class="child-column">
                        <div class="child-name">{{ child.name }}</div>
                        
                        {% if child.timeline %}
                            {% for item in child.timeline %}
                            <div class="timeline-item {{ item.class_name }}">
                                <div class="item-time">{{ item.start_time }} - {{ item.end_time }}</div>
                                <div class="item-title">{{ item.title }}</div>
                                {% if item.notes %}
                                <div class="item-notes">{{ item.notes }}</div>
                                {% endif %}
                            </div>
                            {% endfor %}
                        {% else %}
                            <div class="no-alerts" style="text-align: center; padding: 20px 0;">No activities</div>
                        {% endif %}
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endfor %}
        </div>

        <div class="sidebar">
            <div class="sidebar-card">
                <h3 class="sidebar-title">Active Gaps</h3>
                {% if gaps %}
                    {% for gap in gaps %}
                    <div class="alert-item {% if gap.type == 'ABSOLUTE' %}alert-absolute{% else %}alert-relative{% endif %}">
                        <strong>{{ gap.child_name }}</strong> ({{ gap.date }})<br>
                        {{ gap.start_time }} - {{ gap.end_time }}<br>
                        <span style="font-size: 13px;">{{ gap.description }}</span>
                    </div>
                    {% endfor %}
                {% else %}
                    <div class="no-alerts">No active childcare gaps!</div>
                {% endif %}
            </div>

            <div class="sidebar-card">
                <h3 class="sidebar-title">Disruptions & Warnings</h3>
                {% if disruptions %}
                    {% for dis in disruptions %}
                    <div class="alert-item alert-disruption">
                        <strong>{{ dis.child_name }}</strong> ({{ dis.date }})<br>
                        {{ dis.start_time or "All Day" }} - {{ dis.end_time or "" }}<br>
                        <span style="font-size: 13px;">{{ dis.notes }}</span>
                    </div>
                    {% endfor %}
                {% else %}
                    <div class="no-alerts">No active disruptions.</div>
                {% endif %}
            </div>
        </div>
    </div>

    <script>
        function toggleTheme() {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
        }

        // Set initial theme
        const savedTheme = localStorage.getItem('theme') || 'light';
        document.documentElement.setAttribute('data-theme', savedTheme);
    </script>
</body>
</html>
"""

def generate_html_grid(matrix: Dict[str, Any], profile: Dict[str, Any], output_path: str) -> None:
    """Generate the static HTML dashboard from the schedule matrix and profile."""
    activities = matrix.get("activities", [])
    gaps = matrix.get("gaps", [])
    
    # Extract unique dates from activities and gaps
    dates_set = set()
    for act in activities:
        dates_set.add(act["start_date"])
        dates_set.add(act["end_date"])
    for gap in gaps:
        dates_set.add(gap["date"])
        
    if not dates_set:
        dates_set.add(datetime.now().strftime("%Y-%m-%d"))
        
    # Sort dates
    sorted_dates = sorted(list(dates_set))
    start_date = datetime.strptime(sorted_dates[0], "%Y-%m-%d").date()
    end_date = datetime.strptime(sorted_dates[-1], "%Y-%m-%d").date()
    
    # Build list of days in range
    days_list = []
    current_date = start_date
    children = [c.get("name") for c in profile.get("children", []) if c.get("name")]
    baselines = profile.get("baseline_coverage", [])
    
    # Limit to maximum 31 days to keep local HTML readable
    limit_days = 31
    days_count = 0
    
    while current_date <= end_date and days_count < limit_days:
        if current_date.weekday() < 5: # Weekdays only
            day_str = current_date.strftime("%Y-%m-%d")
            day_name = current_date.strftime("%A, %B %d, %Y")
            
            child_columns = []
            for child in children:
                items = []
                
                # 1. Add school baseline if applicable
                from app.matrix_logic import is_date_in_baseline
                for baseline in baselines:
                    if is_date_in_baseline(current_date, baseline):
                        items.append({
                            "start_time": baseline["start_time"],
                            "end_time": baseline["end_time"],
                            "title": baseline["name"],
                            "class_name": "status-school",
                            "notes": "Baseline school hours"
                        })

                # 2. Add activities for this day
                for act in activities:
                    if act.get("child_name") == child:
                        act_start = datetime.strptime(act["start_date"], "%Y-%m-%d").date()
                        act_end = datetime.strptime(act["end_date"], "%Y-%m-%d").date()
                        
                        if act_start <= current_date <= act_end:
                            status = act.get("status", "ACTIVE")
                            items.append({
                                "start_time": act["start_time"],
                                "end_time": act["end_time"],
                                "title": act["activity_title"],
                                "class_name": "status-active" if status == "ACTIVE" else "status-disrupted",
                                "notes": act.get("notes") or ""
                            })

                # 3. Add gaps for this day
                for gap in gaps:
                    if gap.get("child_name") == child and gap.get("date") == day_str:
                        items.append({
                            "start_time": gap["start_time"],
                            "end_time": gap["end_time"],
                            "title": "Childcare Gap" if gap["type"] == "ABSOLUTE" else "Sibling Care Mismatch",
                            "class_name": "status-gap",
                            "notes": gap.get("description") or ""
                        })
                
                # Sort items by start time
                items.sort(key=lambda x: x["start_time"])
                child_columns.append({
                    "name": child,
                    "timeline": items
                })
                
            days_list.append({
                "name": day_name,
                "children": child_columns
            })
            days_count += 1
            
        current_date += timedelta(days=1)

    # Extract disruptions list
    disruptions = []
    for act in activities:
        if act.get("status") == "DISRUPTED":
            disruptions.append({
                "child_name": act.get("child_name"),
                "date": act.get("start_date"),
                "start_time": act.get("start_time"),
                "end_time": act.get("end_time"),
                "notes": act.get("notes")
            })

    # Render template
    t = Template(HTML_TEMPLATE)
    html_out = t.render(
        days=days_list,
        gaps=gaps,
        disruptions=disruptions
    )
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
