(function () {
  const els = {
    toggle: document.getElementById("chat-toggle"),
    close: document.getElementById("chat-close"),
    window: document.getElementById("chat-window"),
    messages: document.getElementById("chat-messages"),
    form: document.getElementById("chat-form"),
    input: document.getElementById("chat-input"),
  };

  if (!els.toggle || !els.window) return;

  let chatHistory = [];
  try {
    const stored = localStorage.getItem("chat-history");
    if (stored) {
      chatHistory = JSON.parse(stored);
    }
  } catch (e) {
    console.error("Failed to parse chat history:", e);
  }

  // Restore state on load
  const isOpen = localStorage.getItem("chat-open") === "true";
  if (isOpen) {
    document.body.classList.add("chat-open");
  }

  // Scroll to bottom helper
  function scrollToBottom() {
    setTimeout(() => {
      els.messages.scrollTop = els.messages.scrollHeight;
    }, 50);
  }

  // Restore history bubbles
  if (chatHistory.length) {
    for (const msg of chatHistory) {
      addBubble(msg.text, msg.sender, false);
    }
    scrollToBottom();
  }

  // Toggle Chat Window Open (Expand)
  els.toggle.addEventListener("click", () => {
    document.body.classList.add("chat-open");
    localStorage.setItem("chat-open", "true");
    els.input.focus();
    scrollToBottom();
  });

  // Minimize Chat Window (Collapse)
  els.close.addEventListener("click", () => {
    document.body.classList.remove("chat-open");
    localStorage.setItem("chat-open", "false");
  });

  // Basic Markdown Formatter for chat bubbles
  function formatMarkdown(text) {
    let html = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    
    // Bold **text**
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    
    // Inline code `code`
    html = html.replace(/`(.*?)`/g, "<code>$1</code>");
    
    // Lists * or -
    const lines = html.split('\n');
    let inList = false;
    const processedLines = [];
    
    for (let line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('* ') || trimmed.startsWith('- ')) {
        const content = trimmed.substring(2);
        if (!inList) {
          processedLines.push('<ul style="margin: 6px 0; padding-left: 18px;">');
          inList = true;
        }
        processedLines.push(`<li style="margin-bottom: 4px;">${content}</li>`);
      } else {
        if (inList) {
          processedLines.push('</ul>');
          inList = false;
        }
        processedLines.push(line);
      }
    }
    if (inList) {
      processedLines.push('</ul>');
    }
    
    html = processedLines.join('\n');
    // Line breaks
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  function addBubble(text, sender, save = true) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender}`;
    bubble.innerHTML = formatMarkdown(text);
    els.messages.appendChild(bubble);
    els.messages.scrollTop = els.messages.scrollHeight;
    if (save && (sender === "user" || sender === "agent")) {
      chatHistory.push({ text, sender });
      localStorage.setItem("chat-history", JSON.stringify(chatHistory));
    }
    return bubble;
  }

  els.form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const value = els.input.value.trim();
    if (!value) return;

    els.input.value = "";
    addBubble(value, "user");

    // Add typing indicator
    const typingBubble = addBubble("🤖 <i>typing...</i>", "agent typing");

    // Map history payload (exclude the current message we just pushed)
    const apiHistory = chatHistory.slice(0, -1).map(h => ({
      role: h.sender === "user" ? "user" : "model",
      text: h.text
    }));

    try {
      const data = await API.post("/api/chat", { message: value, history: apiHistory });
      typingBubble.remove();
      
      addBubble(data.response, "agent");

      // Trigger portfolio updates on any potential transaction/balance updates
      document.dispatchEvent(new CustomEvent("portfolio:changed"));
    } catch (err) {
      typingBubble.remove();
      addBubble("Sorry, I encountered an error: " + err.message, "system error");
    }
  });
})();
