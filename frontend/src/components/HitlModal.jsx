import { useState } from "react";

export default function HitlModal({ question, onSubmit }) {
    const [response, setResponse] = useState("");

    const handleSubmit = () => {
        const text = response.trim();
        if (!text) return;
        onSubmit(text);
    };

    return (
        <div className="modal-overlay">
            <div className="modal-card">
                <div className="modal-header">
                    <h3>Clarification Required</h3>
                </div>
                <div className="modal-body">
                    <p>{question || "The AI needs some clarification to process this schedule."}</p>
                    <textarea
                        placeholder="Type your response here..."
                        value={response}
                        onChange={(e) => setResponse(e.target.value)}
                    />
                </div>
                <div className="modal-footer">
                    <button className="btn btn-primary" onClick={handleSubmit}>Submit Response</button>
                </div>
            </div>
        </div>
    );
}
