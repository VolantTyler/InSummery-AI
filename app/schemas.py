from pydantic import BaseModel, Field
from typing import List, Optional

class ActivityDetail(BaseModel):
    child_name: str = Field(..., description="Name of the child participating in the activity")
    activity_title: str = Field(..., description="Name or title of the activity (e.g. Soccer Camp, Swimming)")
    start_date: str = Field(..., description="Start date of the activity in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date of the activity in YYYY-MM-DD format")
    start_time: str = Field(..., description="Daily start time of the activity in HH:MM format (24-hour)")
    end_time: str = Field(..., description="Daily end time of the activity in HH:MM format (24-hour)")
    location: Optional[str] = Field(None, description="Location of the activity if specified")
    notes: Optional[str] = Field(None, description="Any additional notes, instructions, or coach names")

class InterpretationResult(BaseModel):
    activities: List[ActivityDetail] = Field(default_factory=list, description="List of extracted activities")
    confidence_score: int = Field(..., description="Confidence score from 0 to 100 on the extraction accuracy")
    evaluation_trace: str = Field(..., description="Brief reasoning trace of why this confidence score was given")

class DisruptionDetail(BaseModel):
    child_name: str = Field(
        ...,
        description=(
            "Name of the affected child. Use an empty string if the message "
            "does not identify a specific child; never invent a name or use 'N/A'."
        ),
    )
    activity_title: Optional[str] = Field(
        None,
        description="Name of the affected activity, camp, or class if the message mentions one",
    )
    date: str = Field(..., description="Date of the disruption in YYYY-MM-DD format")
    start_time: Optional[str] = Field(None, description="Start time of the disruption if applicable (HH:MM)")
    end_time: Optional[str] = Field(None, description="End time of the disruption if applicable (HH:MM)")
    description: str = Field(..., description="Description of the disruption (e.g. nanny sick, camp cancelled)")
    disruption_type: str = Field(..., description="Type of disruption (e.g., CANCELLATION, DELAY, SICK_LEAVE)")
