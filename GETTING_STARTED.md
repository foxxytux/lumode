# Getting Started with Lumo CLI

Welcome! This guide will get you up and running with the Lumo CLI in 5 minutes.

## Step 1: Verify Setup (1 minute)

First, check that everything is installed correctly:

```bash
cd ~/workspace/lumode
python3 test_setup.py
```

You should see ✅ All checks passed!

**If tests fail:** See the troubleshooting section at the bottom.

## Step 2: Ensure Lumo Session (1 minute)

The CLI needs your Lumo session from Firefox:

1. Open Firefox
2. Visit https://lumo.proton.me
3. Log in with your Proton account if needed
4. Close Firefox (optional, but helps free up the cookies.sqlite lock)

## Step 3: Try Your First Query (2 minutes)

### Single Query

Ask Lumo a question:

```bash
./lumo_cli.py -c "Write a Python function that reverses a string"
```

**Expected:** Lumo streams a response token by token. You should see the code appear in real-time.

### Interactive Mode

Start a conversation:

```bash
./lumo_cli.py
```

Then type questions. Type `/quit` to exit.

### Pipe Mode

```bash
echo "Explain Python list comprehensions" | ./lumo_cli.py -c
```

## Examples by Use Case

### Learning to Code

```bash
./lumo_cli.py -p "Explain like I'm a beginner. Use examples." \
  "How do for loops work in JavaScript?"
```

### Code Review

```bash
./lumo_cli.py -c "Review this code for bugs and improvements:

def process_data(items):
    result = []
    for i in range(len(items)):
        if items[i] > 0:
            result.append(items[i] * 2)
    return result"
```

### Debugging

```bash
./lumo_cli.py -c "I'm getting this error: TypeError: 'NoneType' object is not iterable

My function:
def get_items():
    if condition:
        return items"
```

### Advanced: With File Context

```bash
./lumo_advanced.py -c

# Then inside, use these commands:
/file main.py
/file config.json
/exec "npm test"

Then type: "Why is my app crashing?"
```

## Tips

### 🚀 Speed Up

Create aliases in your shell config (`~/.bashrc`, `~/.zshrc`, etc):

```bash
alias lumo='python3 ~/workspace/lumode/lumo_cli.py'
alias lumo-adv='python3 ~/workspace/lumode/lumo_advanced.py'
```

Then you can just type:
```bash
lumo -c "Your question"
```

### 💾 Save Conversations

The CLI doesn't save history, but you can:

```bash
# Pipe output to a file
./lumo_cli.py -c "Question" | tee conversation.txt

# Save from interactive mode with script
script -c './lumo_cli.py'
```

### 🔧 Custom System Prompts

```bash
./lumo_cli.py -p "You are a senior software architect. Focus on design patterns and scalability." \
  "How should I structure this microservice?"
```

### 📚 Multi-turn Conversations

Interactive mode keeps history:

```bash
./lumo_cli.py

# Type your first question
> What is recursion?

# Then follow up questions:
> Can you show a more complex example?
> How is it different from loops?

# Type /quit to exit
```

## Common Questions

### Q: Is my conversation private?

**A:** Yes! Conversations go directly to Proton's servers and are encrypted with zero-knowledge encryption. This CLI doesn't log or store anything.

### Q: How do I stop a response?

**A:** Press `Ctrl+C` - it will interrupt the streaming response.

### Q: Can I use this offline?

**A:** No, you need internet to reach Proton's Lumo servers.

### Q: How long can conversations be?

**A:** Keep them under 20 turns for best performance. Interactive mode stores history in memory (lost when you quit).

### Q: Can I integrate this with my tools?

**A:** Yes! Pipe input from any tool:
```bash
git diff | lumo -c "Explain these changes"
cat error.log | lumo -c "Debug this error"
```

## Troubleshooting

### Problem: "No AUTH cookie found"

**Solution:**
1. Make sure Firefox is closed (to unlock cookies.sqlite)
2. Open Firefox
3. Go to https://lumo.proton.me
4. Log in if needed
5. Close Firefox
6. Try the CLI again

### Problem: "Authentication failed - token may be expired"

**Solution:**
1. Open Firefox
2. Visit https://lumo.proton.me (this refreshes your session)
3. Close Firefox
4. Try the CLI again

### Problem: "API error 403: Access denied"

**Solution:** The Lumo API is in beta testing. You may not have API access yet. Contact Proton support if you believe you should have access.

### Problem: "Connection refused"

**Solution:**
1. Check your internet connection
2. Make sure you can visit https://lumo.proton.me in your browser
3. Try again - servers may be temporarily down

### Problem: Help! Nothing is working!

**Solution:** Run the test again to see what's wrong:

```bash
python3 test_setup.py
```

This will tell you exactly what's misconfigured.

## What to Try Next

1. **Basic mode:** `./lumo_cli.py -c "Your first question"`
2. **Explore examples:** Check `README.md` for more examples
3. **Advanced features:** Try `./lumo_advanced.py -c` with `/file` command
4. **Create alias:** Add to your shell profile for quick access
5. **Integration:** Try piping from other CLI tools

## Files to Read

- **README.md** - Full documentation and examples
- **SETUP.md** - Detailed setup instructions
- **API.md** - Technical API reference
- **API.md** - Developer integration details

## Key Concepts

### Interactive Mode
- Type questions freely
- `/clear` to reset history
- `/quit` to exit
- Ctrl+C to interrupt response

### Single Message Mode
```bash
./lumo_cli.py "Your question"
```
Asks one question and exits.

### Coding Assistant Mode
```bash
./lumo_cli.py -c "Your question"
```
Uses a system prompt optimized for coding tasks.

### Advanced Mode
```bash
./lumo_advanced.py
```
Adds file context with `/file`, `/dir`, `/exec` commands.

## Summary

You're all set! You now have:

✅ A working Lumo CLI
✅ Both basic and advanced modes
✅ Interactive and batch processing
✅ Full documentation

**Next:** Run a simple query!

```bash
./lumo_cli.py -c "Write a hello world in your favorite language"
```

Happy coding! 🚀
