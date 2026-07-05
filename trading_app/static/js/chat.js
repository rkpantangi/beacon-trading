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

  // Toggle Chat Window
  els.toggle.addEventListener("click", () => {
    els.window.hidden = !els.window.hidden;
    if (!els.window.hidden) {
      els.input.focus();
      els.messages.scrollTop = els.messages.scrollHeight;
    }
  });

  els.close.addEventListener("click", () => {
    els.window.hidden = true;
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

  function addBubble(text, sender) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender}`;
    bubble.innerHTML = formatMarkdown(text);
    els.messages.appendChild(bubble);
    els.messages.scrollTop = els.messages.scrollHeight;
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

    try {
      const data = await API.post("/api/chat", { message: value });
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
