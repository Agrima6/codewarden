// Builds CodeWarden_Midterm.pptx. Run: NODE_PATH=<dir with pptxgenjs, react, react-icons, sharp> node build_deck.js
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const OUT = path.join(__dirname, "CodeWarden_Midterm.pptx");
const IMG = (n) => path.join(__dirname, "img", n + ".png");
const ASPECT = { overview: 1.6, review: 1.506, repos: 1.882, exp_top: 1.339, exp_results: 1.159, guardrails: 2.62 };

const THEME = {
  name: "CodeWarden", headFontFace: "Calibri", bodyFontFace: "Calibri",
  colors: { dk1: "111827", lt1: "FFFFFF", dk2: "1F2A44", lt2: "F1F4F9", accent1: "2B59E0", accent2: "187A47",
            accent3: "A77400", accent4: "C4263A", accent5: "52627F", accent6: "6B4FD8", hlink: "2B59E0", folHlink: "52627F" },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5 in
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "CodeWarden: an AI helper that checks code for bugs";
pres.author = "CodeWarden team";
const C = pres.SchemeColor;

// ---- layouts ------------------------------------------------------------------------------------------
pres.defineSlideMaster({
  title: "TITLE_DARK", background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 1.95, w: 6.4, h: 1.2, fontSize: 60, bold: true, color: C.background1, margin: 0, valign: "middle", align: "left" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.7, y: 3.2, w: 6.2, h: 1.0, fontSize: 26, color: C.background1, margin: 0, valign: "top", align: "left" }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT", background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 8.9, h: 0.8, fontSize: 36, bold: true, color: C.text1, margin: 0, valign: "middle", align: "left" }, text: "" } },
    { text: { text: "CodeWarden  |  CSE 4011 mid-term project", options: { x: 0.6, y: 7.02, w: 6, h: 0.3, fontSize: 11, color: C.accent5, margin: 0, isTextBox: true } } },
  ],
  slideNumber: { x: 12.2, y: 7.02, w: 0.55, h: 0.3, fontSize: 11, color: C.accent5, align: "right" },
});
pres.defineSlideMaster({
  title: "CLOSING_DARK", background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 0.4, w: 8.6, h: 0.8, fontSize: 36, bold: true, color: C.background1, margin: 0, valign: "middle", align: "left" }, text: "" } },
  ],
});

// ---- helpers ------------------------------------------------------------------------------------------
async function icon(Comp, color = "FFFFFF") {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: 256 }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}
const shadow = () => ({ type: "outer", color: "000000", blur: 8, offset: 2, angle: 90, opacity: 0.14 });

function chip(slide, text, dark = false) {
  slide.addText(text, {
    x: 9.75, y: 0.5, w: 3.0, h: 0.36, shape: pres.ShapeType.roundRect, rectRadius: 0.18,
    fill: { color: dark ? C.accent1 : C.background2 }, color: dark ? C.background1 : C.accent1,
    fontSize: 12, bold: true, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: "Evaluation tag",
  });
}
function picture(slide, name, x, y, w, alt) {
  const h = w / ASPECT[name], pad = 0.07;
  slide.addShape(pres.ShapeType.roundRect, { x: x - pad, y: y - pad, w: w + 2 * pad, h: h + 2 * pad, rectRadius: 0.08,
    fill: { color: C.background1 }, line: { color: C.background2, width: 1 }, shadow: shadow(), objectName: name + " frame" });
  slide.addImage({ path: IMG(name), x, y, w, h, altText: alt, objectName: name + " screenshot" });
  return h;
}
function caption(slide, text, x, y, w, color = C.accent5) {
  slide.addText(text, { x, y, w, h: 0.4, fontSize: 12, italic: true, color, margin: 0, valign: "top", isTextBox: true });
}
function badge(slide, n, x, y, d, fill) {
  slide.addShape(pres.ShapeType.ellipse, { x, y, w: d, h: d, fill: { color: fill }, objectName: "Number " + n });
  slide.addText(String(n), { x, y, w: d, h: d, fontSize: Math.round(d * 30), bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true });
}
function iconCircle(slide, data, x, y, d, fill, name) {
  slide.addShape(pres.ShapeType.ellipse, { x, y, w: d, h: d, fill: { color: fill }, objectName: name + " circle" });
  const pad = d * 0.25;
  slide.addImage({ data, x: x + pad, y: y + pad, w: d - 2 * pad, h: d - 2 * pad, altText: name, objectName: name + " icon" });
}
const bullets = (items, opts = {}) => items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1, paraSpaceAfter: opts.gap ?? 6 } }));

(async () => {
  const ic = {
    bug: await icon(fa.FaBug), book: await icon(fa.FaBookOpen), shield: await icon(fa.FaShieldAlt), chart: await icon(fa.FaChartBar),
    code: await icon(fa.FaCodeBranch), clock: await icon(fa.FaClock), robot: await icon(fa.FaRobot), warn: await icon(fa.FaExclamationTriangle),
    check: await icon(fa.FaCheck), github: await icon(fa.FaGithub),
  };

  // ============ 1. Title ============
  pres.addSection({ title: "The project" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "The project" });
  s.addText("CSE 4011  |  Mid-term project evaluation", { x: 0.7, y: 1.3, w: 6.4, h: 0.4, fontSize: 15, bold: true, color: C.accent1, margin: 0, isTextBox: true });
  s.addText("CodeWarden", { placeholder: "title" });
  s.addText("An AI helper that checks code for bugs", { placeholder: "body" });
  s.addText("Intelligent Developer Tools and AI DevOps Workflows", { x: 0.7, y: 4.4, w: 6.2, h: 0.4, fontSize: 16, color: C.background2, margin: 0, isTextBox: true });
  s.addText("Presented by: [write your names here]", { x: 0.7, y: 5.3, w: 6.2, h: 0.4, fontSize: 16, color: C.background2, margin: 0, isTextBox: true });
  const h1 = picture(s, "overview", 7.35, 1.95, 5.4, "CodeWarden dashboard overview page");
  caption(s, "The CodeWarden dashboard, running on our laptop", 7.35, 1.95 + h1 + 0.2, 5.4, C.background2);
  s.addNotes(
    "Hello everyone. Our project is called CodeWarden. It is an AI helper that reads a change in code and tells the developer where the bugs and security problems are. " +
    "In the next ten slides we will explain the problem, our goal, how it works, what tools we used, how we tested it, what we found, what went wrong, and how we keep it safe. " +
    "The picture on the right is the real dashboard running on our laptop. Everything you see today is real, not made up."
  );

  // ============ 2. Problem and idea ============
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "The project" });
  s.addText("The problem and our idea", { placeholder: "title" });
  const rows2 = [
    [ic.code, C.accent1, "Code needs a second pair of eyes", "When a developer changes code, another person must read it. This is called a code review."],
    [ic.clock, C.accent3, "It is slow, and people miss things", "Reviewers get tired. Bugs and security problems can slip through."],
    [ic.robot, C.accent2, "Our idea: an AI helper", "CodeWarden reads the change, finds problems, and writes comments on GitHub."],
  ];
  rows2.forEach(([data, color, head, body], i) => {
    const y = 1.6 + i * 1.7;
    iconCircle(s, data, 0.6, y, 0.85, color, head);
    s.addText(head, { x: 1.7, y, w: 5.6, h: 0.45, fontSize: 21, bold: true, color: C.text1, margin: 0, valign: "top", isTextBox: true });
    s.addText(body, { x: 1.7, y: y + 0.5, w: 5.6, h: 0.9, fontSize: 16, color: C.accent5, margin: 0, valign: "top", isTextBox: true });
  });
  const flow = [["A developer changes code", C.background2, C.text1], ["CodeWarden reads it with AI", C.accent1, C.background1], ["Comments appear on the GitHub pull request", C.background2, C.text1]];
  flow.forEach(([t, fill, col], i) => {
    const y = 1.7 + i * 1.95;
    s.addText(t, { x: 8.2, y, w: 4.5, h: 1.15, shape: pres.ShapeType.roundRect, rectRadius: 0.12, fill: { color: fill }, color: col, fontSize: 19, bold: true, align: "center", valign: "middle", margin: 0.1, isTextBox: true, objectName: "Flow box " + (i + 1) });
    if (i < 2) s.addShape(pres.ShapeType.line, { x: 10.45, y: y + 1.2, w: 0, h: 0.7, line: { color: C.accent5, width: 3, endArrowType: "triangle" }, objectName: "Flow arrow " + (i + 1) });
  });
  s.addNotes(
    "When a developer changes code, another person has to read the change and check it. We call this a code review. " +
    "It takes a lot of time, and tired people miss bugs. Our idea is to give them an AI helper. " +
    "The developer changes code. CodeWarden reads it with AI. Then comments with the problems appear on the GitHub pull request, on the exact line. " +
    "The AI is only a first helper. A human still makes the final decision."
  );

  // ============ 3. Objectives ============
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "The project" });
  s.addText("What we wanted to achieve", { placeholder: "title" });
  chip(s, "Research question and goals");
  const goals = [
    [ic.bug, C.accent4, "Find bugs automatically", "Spot bugs and security problems in a code change."],
    [ic.book, C.accent1, "Read the whole project", "Give the AI the related code too. We call this RAG."],
    [ic.shield, C.accent2, "Stay safe", "Hide secrets, block bad advice, and never approve or merge on its own."],
    [ic.chart, C.accent6, "Measure honestly", "Test the AI against a simple checker and report real numbers, even the bad ones."],
  ];
  goals.forEach(([data, color, head, body], i) => {
    const x = 0.6 + (i % 2) * 6.2, y = 1.5 + Math.floor(i / 2) * 2.0;
    s.addShape(pres.ShapeType.roundRect, { x, y, w: 5.9, h: 1.8, rectRadius: 0.1, fill: { color: C.background2 }, objectName: "Goal tile " + (i + 1) });
    iconCircle(s, data, x + 0.3, y + 0.5, 0.8, color, head);
    s.addText(head, { x: x + 1.35, y: y + 0.25, w: 4.4, h: 0.45, fontSize: 21, bold: true, color: C.text1, margin: 0, valign: "top", isTextBox: true });
    s.addText(body, { x: x + 1.35, y: y + 0.78, w: 4.4, h: 0.9, fontSize: 16, color: C.accent5, margin: 0, valign: "top", isTextBox: true });
  });
  s.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 5.7, w: 12.1, h: 1.1, rectRadius: 0.1, fill: { color: C.text1 }, objectName: "Big question band" });
  s.addText([{ text: "Our big question:  ", options: { bold: true, color: C.accent1 } }, { text: "Does the AI find more bugs when it can read the whole project, and not only the small change?", options: { bold: true, color: C.background1 } }],
    { x: 0.9, y: 5.7, w: 11.5, h: 1.1, fontSize: 21, margin: 0, valign: "middle", isTextBox: true });
  s.addNotes(
    "We had four goals. One: find bugs and security problems automatically. Two: let the AI read the whole project, not only the changed lines. This is called RAG, which means the tool looks up related code first and then the AI reads it. " +
    "Three: stay safe. We hide secrets, block bad advice, and the tool can only comment. It can never approve or merge. Four: measure honestly. We test the AI against a simple checker and show real numbers, even when they are not good. " +
    "Our big question is at the bottom: does the AI find more bugs when it can read the whole project?"
  );

  // ============ 4. How it works ============
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "The project" });
  s.addText("How CodeWarden works", { placeholder: "title" });
  chip(s, "Technical implementation");
  const steps = ["Get the code change from GitHub", "Find related code in the project (RAG)", "Hide secrets and personal data", "Ask the AI to find problems", "Check the AI's answer", "Show comments with fixes"];
  steps.forEach((t, i) => {
    const y = 1.55 + i * 0.86;
    badge(s, i + 1, 0.6, y, 0.58, i === 1 ? C.accent2 : C.accent1);
    s.addText(t, { x: 1.4, y, w: 4.5, h: 0.58, fontSize: 18, bold: i === 1, color: C.text1, margin: 0, valign: "middle", isTextBox: true });
  });
  const h4 = picture(s, "review", 6.35, 1.55, 6.35, "A real review in the dashboard with findings on exact lines");
  caption(s, "A real review by the local AI model. Each problem sits on the exact line, with a fix.", 6.35, 1.55 + h4 + 0.18, 6.35);
  s.addNotes(
    "Here is how it works in six steps. One: we get the code change from GitHub. Two: we find related code in the project. This is the RAG step, the green one. " +
    "Three: we hide secrets and personal data. Four: we ask the AI to find problems. Five: we check the AI's answer. For example, every problem must point to a real changed line. Six: we show the comments with suggested fixes. " +
    "The picture is a real review made by our local AI model. You can see the problems on the exact lines, the guardrails panel, and the list of related files that the AI was given."
  );

  // ============ 5. Tools ============
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "The project" });
  s.addText("Tools we used", { placeholder: "title" });
  chip(s, "Technical implementation");
  const head = (t) => ({ text: t, options: { bold: true, color: C.background1, fill: { color: C.accent1 } } });
  const row = (a, b, c) => [{ text: a, options: { bold: true } }, { text: b }, { text: c }];
  s.addTable([
    [head("Part"), head("Tool"), head("What it does")],
    row("Code", "Python and FastAPI", "Runs the tool and the web page"),
    row("AI models", "Qwen2.5-Coder (Ollama), Gemini", "Read code and find bugs"),
    row("Reading the project", "ChromaDB and LangChain", "Look up the related code"),
    row("GitHub", "GitHub API and Actions", "Get pull requests, post comments"),
    row("Memory", "SQLite", "Remembers every review and test"),
    row("Web page", "HTML and JavaScript", "The dashboard you see"),
    row("Testing", "pytest", "146 automatic tests"),
  ], { x: 0.6, y: 1.5, w: 7.3, colW: [1.8, 2.9, 2.6], fontSize: 14, color: C.text1, border: { type: "solid", pt: 0.75, color: C.background2 }, valign: "middle", rowH: 0.55, margin: [0.04, 0.1, 0.04, 0.1], fill: { color: C.background1 }, objectName: "Tools table" });
  const h5 = picture(s, "repos", 8.4, 1.55, 4.3, "Dashboard list of pull requests from a connected GitHub repository");
  caption(s, "Connect any public GitHub repository and review its pull requests.", 8.4, 1.55 + h5 + 0.15, 4.3);
  s.addText([{ text: "Good to know: ", options: { bold: true } }, { text: "all numbers in this talk come from the local Qwen model. Gemini is also built in, but our free key ran out of quota." }],
    { x: 8.4, y: 4.75, w: 4.3, h: 1.65, shape: pres.ShapeType.roundRect, rectRadius: 0.1, fill: { color: C.accent3, transparency: 88 }, color: C.text1, fontSize: 14, margin: 0.15, valign: "middle", isTextBox: true, objectName: "Honesty note" });
  s.addNotes(
    "These are the tools. Python and FastAPI run the tool and the web page. For the AI we use Qwen2.5-Coder, which runs on our own laptop through Ollama, and Google Gemini is also supported. " +
    "For reading the project we use ChromaDB and LangChain. We use the GitHub API to get pull requests and post comments. SQLite remembers every review. The dashboard is plain HTML and JavaScript. We have 146 automatic tests. " +
    "The picture shows the Repositories page. You paste a GitHub address, we copy the project, and then you can pick any of its pull requests to review. " +
    "One honest note: our free Gemini key ran out of quota, so every number in this presentation comes from the local Qwen model."
  );

  // ============ 6. How we tested ============
  pres.addSection({ title: "Testing it" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Testing it" });
  s.addText("How we tested it", { placeholder: "title" });
  chip(s, "Experiment design and method");
  s.addText("Does the AI find more bugs when it can read the whole project?", { x: 0.6, y: 1.45, w: 6.9, h: 1.0, shape: pres.ShapeType.roundRect, rectRadius: 0.1, fill: { color: C.accent1 }, color: C.background1, fontSize: 20, bold: true, margin: 0.2, valign: "middle", isTextBox: true, objectName: "Question box" });
  s.addText("The three helpers", { x: 0.6, y: 2.65, w: 6.9, h: 0.35, fontSize: 16, bold: true, color: C.accent5, margin: 0, isTextBox: true });
  [[C.accent5, "Simple rule checker", " looks for known bad patterns"], [C.accent1, "AI that sees only the change", " reads just the changed lines"], [C.accent2, "AI that also reads the project", " gets the related code too"]].forEach(([color, a, b], i) => {
    const y = 3.08 + i * 0.52;
    s.addShape(pres.ShapeType.ellipse, { x: 0.65, y: y + 0.12, w: 0.2, h: 0.2, fill: { color }, objectName: "Helper dot " + (i + 1) });
    s.addText([{ text: a, options: { bold: true } }, { text: b }], { x: 1.0, y, w: 6.5, h: 0.45, fontSize: 16, color: C.text1, margin: 0, valign: "middle", isTextBox: true });
  });
  s.addText("The two tests", { x: 0.6, y: 4.75, w: 6.9, h: 0.35, fontSize: 16, bold: true, color: C.accent5, margin: 0, isTextBox: true });
  s.addText([
    { text: "Test A: ", options: { bold: true } }, { text: "12 files, 10 hidden bugs you can see in the change", options: { breakLine: true } },
    { text: "Test B: ", options: { bold: true } }, { text: "7 files, 6 hidden bugs you can only find by knowing the project" },
  ], { x: 0.6, y: 5.12, w: 6.9, h: 1.0, fontSize: 16, color: C.text1, margin: 0, valign: "top", paraSpaceAfter: 6, isTextBox: true });
  s.addText("We put every bug there on purpose, so we know where it is. Each helper tried 3 times.", { x: 0.6, y: 6.2, w: 6.9, h: 0.6, fontSize: 14, italic: true, color: C.accent5, margin: 0, valign: "top", isTextBox: true });
  const h6 = picture(s, "exp_top", 8.05, 1.55, 4.65, "Experiment page of the dashboard explaining the question");
  caption(s, "The Experiment page in the dashboard", 8.05, 1.55 + h6 + 0.18, 4.65);
  s.addNotes(
    "Here is how we tested. Our question: does the AI find more bugs when it can read the whole project? " +
    "We wrote 19 small files. 16 of them have a bug that we put there on purpose, so we know exactly where every bug is. A few files have no bug at all, to see if a helper makes false alarms. " +
    "We compare three helpers. First, a simple rule checker, which looks for known bad patterns. It is our control, the one we want to beat. Second, the AI that sees only the change. Third, the same AI that also reads the project. " +
    "There are two tests. Test A has bugs you can see in the change. Test B has bugs you can only find if you know the rest of the project, for example how a helper function works. " +
    "Because an AI does not always answer the same way, each helper tried three times. The page on the right is the Experiment page in our dashboard."
  );

  // ============ 7. Results ============
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Testing it" });
  s.addText("What we found", { placeholder: "title" });
  chip(s, "Quantitative results");
  [["83% vs 60%", C.accent1, "Test A: the AI found more hidden bugs than the simple rule checker"],
   ["50% to 72%", C.accent2, "Test B: reading the project helped the AI find more bugs"],
   ["3 to 1", C.accent3, "False alarms went down when the AI read the project"]].forEach(([big, color, label], i) => {
    const y = 1.5 + i * 1.45;
    s.addText(big, { x: 0.6, y, w: 5.9, h: 0.75, fontSize: 44, bold: true, color, margin: 0, valign: "middle", isTextBox: true, objectName: "Stat " + (i + 1) });
    s.addText(label, { x: 0.6, y: y + 0.75, w: 5.9, h: 0.55, fontSize: 16, color: C.text1, margin: 0, valign: "top", isTextBox: true });
  });
  s.addText([{ text: "Looks good, but not proven. ", options: { bold: true } }, { text: "We only had a few test bugs, so the likely ranges overlap and luck could play a part." }],
    { x: 0.6, y: 5.85, w: 5.9, h: 1.0, shape: pres.ShapeType.roundRect, rectRadius: 0.1, fill: { color: C.accent3, transparency: 88 }, color: C.text1, fontSize: 15, margin: 0.15, valign: "middle", isTextBox: true, objectName: "Verdict" });
  const h7 = picture(s, "exp_results", 7.0, 1.5, 5.7, "Scoreboard from the dashboard showing how many hidden bugs each helper found");
  caption(s, "Scoreboard from our dashboard. Local AI: qwen2.5-coder 7B, 3 tries per file.", 7.0, 1.5 + h7 + 0.15, 5.7);
  s.addNotes(
    "These are our real results. In Test A, the AI found 83 percent of the hidden bugs. The simple rule checker found 60 percent. So the AI did better. " +
    "In Test B, the rule checker found none, because rules cannot see the rest of the project. The AI that sees only the change found 50 percent. When it also read the project, it found 72 percent. Reading the project helped. " +
    "The false alarms also went down, from 3 to 1. " +
    "But please note the yellow box. We only had a few test bugs, so the likely ranges of the scores overlap. That means we cannot be sure it is not luck. We say: it looks good, but it is not proven. A bigger test would give a firmer answer. " +
    "Note for questions: we count each bug once. Running the same file three times shows how much the AI changes its answer, but it is not three new pieces of evidence."
  );

  // ============ 8. What went wrong ============
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Testing it" });
  s.addText("What went wrong, and what to watch", { placeholder: "title" });
  chip(s, "Limitations and failure analysis");
  const panel = (x, w, color, data, head, items, name) => {
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.5, w, h: 5.2, rectRadius: 0.1, fill: { color, transparency: 92 }, objectName: name + " panel" });
    iconCircle(s, data, x + 0.3, 1.75, 0.65, color, name);
    s.addText(head, { x: x + 1.1, y: 1.75, w: w - 1.4, h: 0.65, fontSize: 21, bold: true, color: C.text1, margin: 0, valign: "middle", isTextBox: true });
    s.addText(bullets(items, { gap: 9 }), { x: x + 0.35, y: 2.7, w: w - 0.7, h: 3.8, fontSize: 18, color: C.text1, margin: 0, valign: "top", isTextBox: true });
  };
  panel(0.6, 6.0, C.accent4, ic.bug, "Where the AI made mistakes", [
    "It never found the race-condition bug (0 of 3 tries).",
    "It called safe code \"SQL injection\" in 2 of 3 tries. That is a false alarm.",
    "Reading the project did not always help: one bug went from 3 found to 1 found.",
    "It missed a call to a helper that does not exist, even when it read the project.",
  ], "Mistakes");
  panel(6.9, 5.8, C.accent3, ic.warn, "Be careful about", [
    "Only 16 test bugs, so results can change.",
    "We wrote the tests and the simple checker ourselves.",
    "Practice bugs are neater than real bugs.",
    "The AI can answer differently each time.",
    "A longer message may also help, not only the useful code.",
  ], "Care");
  s.addNotes(
    "We want to be honest about the problems. These are real examples from our test, not made up. " +
    "The AI never found the race-condition bug. On safe code, it sometimes shouted \"SQL injection\", which is a false alarm. It happened in 2 of 3 tries. " +
    "Reading the project did not always help. For one bug, the AI found it 3 times without the project, but only 1 time with the project. And for a call to a helper function that does not exist, it found nothing in either case. " +
    "On the right are things to be careful about. We had only 16 test bugs. We wrote the tests and the simple checker ourselves, so someone else might make a harder test. Real bugs are messier than our practice bugs. The AI changes its answer from run to run. And the project-reading AI also gets a longer message, so part of the gain might come from that."
  );

  // ============ 9. Guardrails ============
  pres.addSection({ title: "Safety and wrap-up" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Safety and wrap-up" });
  s.addText("Staying safe: guardrails", { placeholder: "title" });
  chip(s, "Technical implementation");
  const layers = [
    ["1  Input", C.accent1, ["Hide secrets and personal data", "Never send files like .env", "Catch tricky instructions"]],
    ["2  Model", C.accent6, ["Answer must follow the format", "Must point to a real changed line", "Drop low-confidence guesses"]],
    ["3  Output", C.accent2, ["Remove links, images, @mentions", "Block unsafe fix suggestions", "Hide any key the AI repeats"]],
    ["4  Action", C.accent4, ["Comment only, never approve", "Asks you before posting", "Limit on posts per hour"]],
  ];
  layers.forEach(([name, color, items], i) => {
    const x = 0.6 + i * 3.08;
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.45, w: 2.85, h: 2.35, rectRadius: 0.1, fill: { color }, objectName: "Layer " + (i + 1) });
    s.addText(name, { x: x + 0.2, y: 1.55, w: 2.45, h: 0.5, fontSize: 20, bold: true, color: C.background1, margin: 0, valign: "middle", isTextBox: true });
    s.addText(bullets(items, { gap: 4 }), { x: x + 0.2, y: 2.1, w: 2.5, h: 1.6, fontSize: 14, color: C.background1, margin: 0, valign: "top", isTextBox: true });
  });
  const h9 = picture(s, "guardrails", 0.6, 4.05, 6.7, "Guardrail tester showing a password and an email hidden and a trick instruction removed");
  caption(s, "Live in the dashboard: the password and email are hidden, and the trick instruction is removed.", 0.6, 4.05 + h9 + 0.14, 7.2);
  s.addText("15 rules", { x: 8.0, y: 4.05, w: 4.7, h: 0.8, fontSize: 40, bold: true, color: C.accent1, margin: 0, valign: "middle", isTextBox: true, objectName: "Rule count" });
  s.addText("in 4 layers. Type any text on the Guardrails page and see what they do.", { x: 8.0, y: 4.9, w: 4.7, h: 0.9, fontSize: 16, color: C.text1, margin: 0, valign: "top", isTextBox: true });
  s.addText("They lower the risk, but they do not remove it. A human still decides.", { x: 8.0, y: 5.85, w: 4.7, h: 0.8, fontSize: 14, italic: true, color: C.accent5, margin: 0, valign: "top", isTextBox: true });
  s.addNotes(
    "An AI reads code from strangers and writes text that gets published, so we put guardrails on all four sides. " +
    "Input: we hide secrets like passwords and keys, we hide personal data like emails, we never send files like dot-env, and we catch tricky instructions hidden in the code. " +
    "Model: the answer must follow our format, and every problem must point to a real changed line. " +
    "Output: we remove links, images and mentions, block unsafe fix suggestions, and hide any key the AI repeats. " +
    "Action: the tool can only comment. It can never approve or merge. It asks before posting, and there is a limit on posts per hour. " +
    "The picture is the live tester in the dashboard. We typed a password, an email and a trick instruction. The password and email were hidden and the trick instruction was removed before the AI saw it. " +
    "Be honest: these checks use patterns, so they lower the risk but do not remove it."
  );

  // ============ 10. Repeat and next ============
  s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Safety and wrap-up" });
  s.addText("Repeat it, and what comes next", { placeholder: "title" });
  chip(s, "Methodology and reproducibility", true);
  s.addText("Repeat our test", { x: 0.7, y: 1.55, w: 6.0, h: 0.5, fontSize: 22, bold: true, color: C.accent1, margin: 0, isTextBox: true });
  s.addText(bullets([
    "Same 19 test files and same instructions (saved version numbers)",
    "One command runs everything:",
  ], { gap: 8 }), { x: 0.7, y: 2.15, w: 6.0, h: 1.4, fontSize: 17, color: C.background1, margin: 0, valign: "top", isTextBox: true });
  s.addText("codewarden experiment --providers rules,ollama --repeats 3", { x: 0.7, y: 3.45, w: 6.4, h: 0.6, shape: pres.ShapeType.roundRect, rectRadius: 0.08, fill: { color: C.text2 }, color: C.background1, fontFace: "Courier New", fontSize: 12, margin: 0.15, valign: "middle", isTextBox: true, objectName: "Command" });
  s.addText(bullets([
    "Results are saved as JSON and CSV files",
    "146 automatic tests check the code",
  ], { gap: 8 }), { x: 0.7, y: 4.4, w: 6.0, h: 1.2, fontSize: 17, color: C.background1, margin: 0, valign: "top", isTextBox: true });
  s.addText("What we would do next", { x: 7.3, y: 1.55, w: 5.4, h: 0.5, fontSize: 22, bold: true, color: C.accent1, margin: 0, isTextBox: true });
  s.addText(bullets([
    "A bigger test set, with real bugs from real projects",
    "Try bigger AI models",
    "Compare the AI with human reviewers",
    "Test more programming languages",
  ], { gap: 10 }), { x: 7.3, y: 2.15, w: 5.4, h: 3.2, fontSize: 17, color: C.background1, margin: 0, valign: "top", isTextBox: true });
  s.addText("Thank you. Questions?", { x: 0.7, y: 6.0, w: 12.0, h: 0.9, fontSize: 38, bold: true, color: C.background1, margin: 0, valign: "middle", isTextBox: true });
  s.addNotes(
    "Anyone can repeat our test. The test files and the instructions have saved version numbers. One command runs everything, and the results are saved as JSON and CSV files. The code has 146 automatic tests. " +
    "Next we would like a bigger test set with real bugs from real projects, try bigger AI models, compare the AI with human reviewers, and test more programming languages. " +
    "Thank you. We are happy to answer questions. " +
    "Question tips: if asked why we trust the result, say it looks good but is not proven, because we had few test bugs. If asked which model, say the local Qwen2.5-Coder 7B through Ollama. If asked about Gemini, say it is supported but our free quota ran out, so no Gemini numbers are reported."
  );

  await pres.writeFile({ fileName: OUT });
  console.log("wrote", OUT);
})();
