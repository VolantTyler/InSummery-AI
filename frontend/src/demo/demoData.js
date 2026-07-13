/** Preloaded demo family, schedules, and sample registration emails. */

export const DEMO_STORAGE_KEY = "insummery_demo_mode";
export const DEMO_MATRIX_KEY = "insummery_demo_matrix";

export const DEMO_USER = {
    email: "demo@insummery.local",
    displayName: "Demo Family",
    isDemo: true,
    getIdToken: async () => "demo-local-token",
};

export const DEMO_PROFILE = {
    parents: [
        {
            name: "Jordan Okonkwo",
            email: "jordan.okonkwo@example.com",
            phone: "555-214-8801",
        },
        {
            name: "Avery Chen",
            email: "avery.chen@example.com",
            phone: "555-214-8802",
        },
    ],
    children: [
        { name: "Remy", age: 10 },
        { name: "Quinn", age: 8 },
        { name: "Sage", age: 6 },
        { name: "Kai", age: 12 },
    ],
    address: "482 Maple Crescent, Harborview",
    baseline_coverage: [
        {
            name: "School",
            days: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            start_time: "08:30",
            end_time: "15:00",
            months: [
                "September",
                "October",
                "November",
                "December",
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
            ],
        },
    ],
    google_calendar_connected: false,
    onboarding_required: false,
};

/** Four summer weeks spanning July and August 2026 for Remy and Quinn. */
export function buildSeedActivities() {
    return [
        {
            id: "demo-remy-01",
            child_name: "Remy",
            activity_title: "Harbor Strikers Soccer Camp",
            start_date: "2026-07-06",
            end_date: "2026-07-10",
            start_time: "09:00",
            end_time: "12:00",
            location: "Harborview Athletic Fields, Pitch 2",
            notes: "Bring shin guards, water bottle, and a morning snack. Drop-off opens at 8:45 AM.",
            status: "ACTIVE",
        },
        {
            id: "demo-remy-02",
            child_name: "Remy",
            activity_title: "Bay Swim Club",
            start_date: "2026-07-13",
            end_date: "2026-07-17",
            start_time: "09:00",
            end_time: "15:00",
            location: "Harborview Aquatic Center, Lane Pool B",
            notes: "Pack a peanut-free lunch, towel, and sunscreen. Cap required for all pool sessions.",
            status: "ACTIVE",
        },
        {
            id: "demo-remy-03",
            child_name: "Remy",
            activity_title: "Studio Clay & Color",
            start_date: "2026-07-27",
            end_date: "2026-07-31",
            start_time: "10:00",
            end_time: "15:00",
            location: "Riverside Arts Collective, Studio 4",
            notes: "Wear clothes that can get messy. Afternoon pickup is at the north courtyard.",
            status: "ACTIVE",
        },
        {
            id: "demo-remy-04",
            child_name: "Remy",
            activity_title: "Pixel Builders Coding Week",
            start_date: "2026-08-03",
            end_date: "2026-08-07",
            start_time: "13:00",
            end_time: "16:00",
            location: "Sci-Tech Discovery Lab, Room 118",
            notes: "Laptop provided. Snack break at 2:30 PM. Authorized pickup only.",
            status: "ACTIVE",
        },
        {
            id: "demo-quinn-01",
            child_name: "Quinn",
            activity_title: "Little Trails Nature Camp",
            start_date: "2026-07-06",
            end_date: "2026-07-10",
            start_time: "09:00",
            end_time: "12:00",
            location: "Cedar Grove Conservancy, Trailhead Lodge",
            notes: "Closed-toe shoes required. Bug spray applied at home before drop-off.",
            status: "ACTIVE",
        },
        {
            id: "demo-quinn-02",
            child_name: "Quinn",
            activity_title: "Junior Racquet Camp",
            start_date: "2026-07-13",
            end_date: "2026-07-17",
            start_time: "13:30",
            end_time: "16:30",
            location: "Harbor Tennis Club, Courts 5–6",
            notes: "Racket provided if needed. Bring a labeled water bottle and hat.",
            status: "ACTIVE",
        },
        {
            id: "demo-quinn-03",
            child_name: "Quinn",
            activity_title: "Stagecraft Theater Week",
            start_date: "2026-07-27",
            end_date: "2026-07-31",
            start_time: "09:00",
            end_time: "14:00",
            location: "Civic Playhouse Rehearsal Hall",
            notes: "Friday family showcase at 1:00 PM in the main theater.",
            status: "ACTIVE",
        },
        {
            id: "demo-quinn-04",
            child_name: "Quinn",
            activity_title: "Harbor Strings Music Camp",
            start_date: "2026-08-03",
            end_date: "2026-08-07",
            start_time: "09:00",
            end_time: "12:00",
            location: "Community Music School, Room 3B",
            notes: "Instrument rentals available at the front desk. Bring a music stand if you have one.",
            status: "ACTIVE",
        },
    ];
}

export const DEMO_SAMPLE_EMAILS = [
    {
        id: "complete",
        label: "Complete registration (Sage)",
        description: "All key fields present — parses with high confidence and adds Sage’s week.",
        hitlExpected: false,
        text: `Subject: Registration Confirmation — Little Explorers Day Camp
Date: Wed, 24 Jun 2026 10:22:41 -0400
From: camps@cedar-grove.org
To: jordan.okonkwo@example.com

Dear Jordan and Avery,

Thank you for registering Sage Okonkwo-Chen for Little Explorers Day Camp.

---------------------------------------------------------
REGISTRATION SUMMARY
---------------------------------------------------------
Child: Sage Okonkwo-Chen
Program: Little Explorers Day Camp (Ages 5–7)
Dates: Monday, August 10, 2026 to Friday, August 14, 2026
Times: 9:00 AM – 12:00 PM daily
Location: Cedar Grove Conservancy, Willow Classroom
Address: 220 Conservancy Road, Harborview
Lead Counselor: Priya Nair (camps@cedar-grove.org)
Status: PAID IN FULL
---------------------------------------------------------

Parent notes:
1. Drop-off begins at 8:50 AM at the Willow Classroom porch.
2. Pack a labeled water bottle and a morning snack (nut-free).
3. Wear closed-toe shoes suitable for short nature walks.

If you have questions, reply to this email or call 555-430-2290.

Warm regards,
Cedar Grove Summer Programs
`,
    },
    {
        id: "incomplete",
        label: "Incomplete registration (Kai) — triggers confirmation",
        description: "Omits end date and end time so the concierge asks you to confirm details.",
        hitlExpected: true,
        text: `Subject: Booking received — Youth Leadership Summit
Date: Thu, 25 Jun 2026 16:05:12 -0400
From: registrar@harboru.edu
To: avery.chen@example.com

Hi Avery,

We received Kai Okonkwo-Chen’s registration for the Youth Leadership Summit.

=========================================
BOOKING DETAILS
=========================================
Attendee: Kai Okonkwo-Chen
Program: Youth Leadership Summit (Ages 11–14)
Start Date: Monday, August 10, 2026
Start Time: 9:00 AM
Location: Harbor University Student Center, Room 210
Address: 1 University Way, Harborview

Payment: $285.00 received (Visa ending 4410)

Please review your confirmation packet when it arrives. Campus maps and the packing list are attached on our portal.

Thanks,
Harbor University Youth Programs
registrar@harboru.edu
`,
    },
];

/** Activity applied after the complete Sage email is ingested. */
export const DEMO_SAGE_ACTIVITY = {
    child_name: "Sage",
    activity_title: "Little Explorers Day Camp",
    start_date: "2026-08-10",
    end_date: "2026-08-14",
    start_time: "09:00",
    end_time: "12:00",
    location: "Cedar Grove Conservancy, Willow Classroom",
    notes: "Drop-off 8:50 AM. Nut-free snack and labeled water bottle required.",
};

/** Partial activity for Kai — end_date/end_time filled after HITL. */
export const DEMO_KAI_PARTIAL = {
    child_name: "Kai",
    activity_title: "Youth Leadership Summit",
    start_date: "2026-08-10",
    start_time: "09:00",
    location: "Harbor University Student Center, Room 210",
    notes: "Campus program; packing list available on the university portal.",
};

export const DEMO_HITL_QUESTION =
    "I found Kai’s Youth Leadership Summit starting Monday, August 10, 2026 at 9:00 AM, but the registration email is missing the end date and end time. What is the end date and end time for this program?";
