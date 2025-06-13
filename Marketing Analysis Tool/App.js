import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';

function App() {
  const [company, setCompany] = useState('');
  const [chat, setChat] = useState([]);
  const [loading, setLoading] = useState(false);
  const [followUp, setFollowUp] = useState('');

  const handleStartChat = async () => {
    if (!company.trim()) return;
    setLoading(true);

    const response = await fetch('http://localhost:8000/start_chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company }),
    });

    const data = await response.json();
    setChat([{ role: 'bot', text: data.insight }]);
    setLoading(false);
  };

  const handleFollowUp = async () => {
    if (!followUp.trim()) return;
    setLoading(true);

    const response = await fetch('http://localhost:8000/follow_up', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: followUp }),
    });

    const data = await response.json();
    setChat(prev => [...prev, { role: 'user', text: followUp }, { role: 'bot', text: data.reply }]);
    setFollowUp('');
    setLoading(false);
  };

  return (
    <div style={{ padding: '20px', maxWidth: '600px', margin: 'auto' }}>
      <h2>Marketing & Finance Chatbot</h2>

      <input
        type="text"
        placeholder="Enter company name..."
        value={company}
        onChange={e => setCompany(e.target.value)}
        style={{ width: '100%', padding: '8px', marginBottom: '10px' }}
      />
      <button onClick={handleStartChat} disabled={loading}>
        {loading ? 'Loading...' : 'Get Insights'}
      </button>

      <div style={{ marginTop: '20px', border: '1px solid #ddd', padding: '10px', height: '300px', overflowY: 'scroll' }}>
        {chat.map((msg, idx) => (
          <div key={idx} style={{ textAlign: msg.role === 'user' ? 'right' : 'left' }}>
            <b>{msg.role === 'user' ? 'You' : 'Bot'}:</b>
            {msg.role === 'bot' ? (
              <ReactMarkdown>{msg.text}</ReactMarkdown>
            ) : (
              <p>{msg.text}</p>
            )}
          </div>
        ))}
      </div>

      {chat.length > 0 && (
        <>
          <input
            type="text"
            placeholder="Ask a follow-up..."
            value={followUp}
            onChange={e => setFollowUp(e.target.value)}
            style={{ width: '100%', padding: '8px', marginTop: '10px' }}
          />
          <button onClick={handleFollowUp} disabled={loading}>
            {loading ? 'Loading...' : 'Send Follow-up'}
          </button>
        </>
      )}
    </div>
  );
}

export default App;
