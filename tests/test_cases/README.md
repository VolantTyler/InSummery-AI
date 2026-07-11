# InSummery Test Cases Suite

This directory contains a curated set of **10 test cases** featuring different kids, camps, schedules, and email formats. These cases are designed to test the robustness of the InSummery schedule parser, the PII masking/unmasking framework, the schedule matrix merging logic, and Google Calendar syncing.

## Test Family Profile

All test cases are based on the family profile defined in [profile_10_kids.json](file:///c:/Users/tyler/Git/InSummery-AI/tests/test_cases/profile_10_kids.json). To use these test cases, copy this file to `config/profile.json` before running the CLI, or import it into the Web App dashboard.

### Profile Summary:
- **Parents**: Dana & Jamie
- **Caregivers**: Avery (Nanny) & Drew (Sitter)
- **Home Address**: `555 Pine Lane, Springville`
- **Children (10)**:
  1. **Pat** (Age 10)
  2. **Sam** (Age 8)
  3. **Alex** (Age 12)
  4. **Jordan** (Age 7)
  5. **Riley** (Age 9)
  6. **Casey** (Age 11)
  7. **Quinn** (Age 5)
  8. **Morgan** (Age 6)
  9. **Taylor** (Age 13)
  10. **Reese** (Age 14)

---

## Test Cases Overview

The ground truth metadata for each case is defined in [test_cases_manifest.json](file:///c:/Users/tyler/Git/InSummery-AI/tests/test_cases/test_cases_manifest.json).

| ID | Child | Camp / Activity | Dates | Times | Edge Case / Testing Focus |
|---|---|---|---|---|---|
| **01** | Pat | Junior Striker Soccer Camp | Jul 6 – Jul 10, 2026 | 09:00 - 12:00 | Standard morning camp, matches first child in profile. |
| **02** | Sam | Astro Academy Space & Robotics | Jul 13 – Jul 17, 2026 | 09:00 - 15:00 | Full-day camp, contains numeric Order IDs and detailed pick-up lists. |
| **03** | Alex | Teen Fine Arts Intensive | Jul 6 – Jul 17, 2026 | 10:00 - 16:00 | **2-Week Camp**. Tests multi-week parsing and 10:00-16:00 times. |
| **04** | Jordan | Wilderness Survival Camp | Jul 20 – Jul 24, 2026 | 08:30 - 16:30 | Long hours, specific drop-off checkpoint name. Tests detailed notes extraction. |
| **05** | Riley | Broadway Bound Theater Camp | Jul 27 – Aug 7, 2026 | 09:00 - 14:00 | **2-Week Camp with schedule exception**. The final Friday has an evening show (6:00 - 8:30 PM). Tests exception handling. |
| **06** | Casey | Roblox Game Design & Coding | Jun 29 – Jul 3, 2026 | 13:00 - 16:00 | **Afternoon-only session**. Starts in late June, ends in July. Tests boundary dates. |
| **07** | Quinn | Little Explorers Day Camp | Jul 13 – Jul 17, 2026 | 09:00 - 12:00 | Half-day camp, younger age group, includes classroom letter names. |
| **08** | Morgan | Junior Tennis Camp | Jul 20 – Jul 24, 2026 | 13:30 - 16:30 | Afternoon camp starting on a half-hour. Tests 24h clock conversion for 1:30 PM. |
| **09** | Taylor | Youth Leadership Summit | Aug 3 – Aug 7, 2026 | 09:00 - 17:00 | Full-day university summit. Tests long notes extraction and formal letter formatting. |
| **10** | Reese | Elite Hoops Basketball Clinic | Jul 27 – Jul 31, 2026 | 08:00 - 11:00 | **Forwarded email format**. Tests nested email/SMS thread header extraction and early morning times (8:00 AM). |

---

## How to Test

### 1. Set Up the Test Profile
Overwrite the active profile with the 10-kid profile:
```bash
cp tests/test_cases/profile_10_kids.json config/profile.json
```

### 2. Ingest Single Test Cases via the CLI
Run individual files through the CLI in local mode to verify extraction, data-masking, and local HTML layout rendering:
```bash
python bin/insummery --mode local --input "$(cat tests/test_cases/case_01_pat_soccer.txt)"
```
*(On Windows PowerShell, use: `python bin/insummery --mode local --input (Get-Content tests/test_cases/case_01_pat_soccer.txt -Raw)`)*

Verify:
- The output file [output/schedule.html](file:///c:/Users/tyler/Git/InSummery-AI/output/schedule.html) opens and displays the new event correctly under Pat's column.
- The console log demonstrates PII masking (names, emails, phones replaced with `[CHILD_A]`, `[EMAIL_1]`, etc. before LLM ingestion, then restored to the original values).

### 3. Verify Childcare Gap Analysis
With multiple camps registered (e.g., Pat at soccer Jul 6-10 and Alex at art Jul 6-17), open the local dashboard and verify:
- **Absolute Gaps** are highlighted where a child has no scheduled activity between 9 AM - 5 PM on weekdays.
- **Relative Gaps** are highlighted (e.g., showing sibling schedule mismatches where Pat has camp but Sam or Quinn does not).
