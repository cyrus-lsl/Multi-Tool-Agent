import React, { useState, useRef, useEffect } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";


function App() {
  const [query, setQuery] = useState("");
  const [chatHistory, setChatHistory] = useState([]);
  const messagesEndRef = useRef(null);

  // Load from localStorage on first load
  useEffect(() => {
    const stored = localStorage.getItem("chatHistory");
    if (stored) {
      setChatHistory(JSON.parse(stored));
    }
  }, []);

  // Save chat history to localStorage
  useEffect(() => {
    localStorage.setItem("chatHistory", JSON.stringify(chatHistory));
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;

    const userMessage = { sender: "user", text: query };
    setChatHistory((prev) => [...prev, userMessage]);
    setQuery("");

    try {
      const res = await axios.post("http://localhost:8000/query", { query });
      const rawReply = res.data.reply || res.data.insight || JSON.stringify(res.data, null, 2);
      const cleanReply = rawReply;
      const botMessage = { sender: "bot", text: cleanReply };
      setChatHistory((prev) => [...prev, botMessage]);
    } catch (err) {
      setChatHistory((prev) => [
        ...prev,
        { sender: "bot", text: "Something went wrong." },
      ]);
    }
  };

  const handleClear = () => {
    setChatHistory([]);
    localStorage.removeItem("chatHistory");
  };

  return (
    <div style={styles.container}>
      <h2 style={styles.header}>AI Chatbot</h2>
      
      <div style={styles.chatBox}>
        {chatHistory.map((msg, idx) => (
          <div key={idx} style={msg.sender === "user" ? styles.userMsg : styles.botMsg}>
            <div><strong>{msg.sender === "user" ? "You" : "AI"}:</strong></div>
            <ReactMarkdown>{msg.text}</ReactMarkdown>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <button onClick={handleClear} style={styles.clearButton}>Clear Chat</button>

      <form onSubmit={handleSubmit} style={styles.form}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask anything..."
          style={styles.input}
        />
        <button type="submit" style={styles.button}>Send</button>
      </form>
    </div>
  );
}

const styles = {
  container: {
    maxWidth: 600,
    margin: "0 auto",
    padding: 20,
    fontFamily: "Arial, sans-serif"
  },
  header: {
    textAlign: "center"
  },
  chatBox: {
    height: "60vh",
    overflowY: "auto",
    border: "1px solid #ccc",
    borderRadius: 8,
    padding: 10,
    backgroundColor: "#f9f9f9",
    marginBottom: 10
  },
  userMsg: {
    backgroundColor: "#d1e7dd",
    padding: 10,
    borderRadius: 6,
    marginBottom: 10,
    alignSelf: "flex-end"
  },
  botMsg: {
    backgroundColor: "#e2e3e5",
    padding: 10,
    borderRadius: 6,
    marginBottom: 10,
    alignSelf: "flex-start"
  },
  form: {
    display: "flex",
    gap: 10
  },
  input: {
    flex: 1,
    padding: 10,
    borderRadius: 4,
    border: "1px solid #ccc"
  },
  button: {
    padding: "10px 16px",
    borderRadius: 4,
    border: "none",
    backgroundColor: "#007bff",
    color: "white",
    cursor: "pointer"
  },
  clearButton: {
    marginBottom: 10,
    padding: "8px 12px",
    borderRadius: 4,
    border: "none",
    backgroundColor: "#dc3545",
    color: "white",
    cursor: "pointer"
  }
};

export default App;
