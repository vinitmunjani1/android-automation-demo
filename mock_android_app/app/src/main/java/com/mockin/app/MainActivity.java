package com.mockin.app;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

public class MainActivity extends Activity {
    private final int BLUE = Color.rgb(10, 102, 194);
    private final int BG = Color.rgb(243, 242, 239);
    private final int TEXT = Color.rgb(25, 25, 25);
    private final int MUTED = Color.rgb(102, 102, 102);
    private final int BORDER = Color.rgb(222, 226, 230);
    private final int SEARCH_BG = Color.rgb(237, 243, 248);

    private LinearLayout feedList;
    private LinearLayout resultsList;
    private LinearLayout profilePage;
    private EditText searchInput;

    private final List<Person> people = new ArrayList<>();

    static class Person {
        String name, title, company;
        Person(String name, String title, String company) {
            this.name = name; this.title = title; this.company = company;
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        seedPeople();
        setContentView(buildUi());
        renderFeed();
    }

    private View buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);

        root.addView(topBar());

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(false);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(0, dp(8), 0, dp(84));

        content.addView(startPostCard());

        feedList = new LinearLayout(this);
        feedList.setId(R.id.feed_list);
        feedList.setOrientation(LinearLayout.VERTICAL);
        feedList.setContentDescription("Feed list");

        resultsList = new LinearLayout(this);
        resultsList.setId(R.id.results_list);
        resultsList.setOrientation(LinearLayout.VERTICAL);
        resultsList.setContentDescription("Search results");

        profilePage = new LinearLayout(this);
        profilePage.setId(R.id.profile_page);
        profilePage.setOrientation(LinearLayout.VERTICAL);
        profilePage.setVisibility(View.GONE);
        profilePage.setContentDescription("Profile page");

        content.addView(feedList);
        content.addView(resultsList);
        content.addView(profilePage);
        scroll.addView(content);
        root.addView(scroll, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));
        root.addView(bottomNav());

        searchInput.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) { renderResults(s.toString()); }
            @Override public void afterTextChanged(Editable s) {}
        });

        return root;
    }

    private LinearLayout topBar() {
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(10), dp(8), dp(10), dp(8));
        header.setBackgroundColor(Color.WHITE);

        TextView avatar = avatar("M", dp(38));
        avatar.setContentDescription("Profile menu");
        header.addView(avatar);

        searchInput = new EditText(this);
        searchInput.setId(R.id.search_input);
        searchInput.setHint("Search");
        searchInput.setSingleLine(true);
        searchInput.setContentDescription("Search people");
        searchInput.setTextSize(15);
        searchInput.setTextColor(TEXT);
        searchInput.setHintTextColor(MUTED);
        searchInput.setPadding(dp(14), 0, dp(14), 0);
        searchInput.setBackground(rounded(SEARCH_BG, 0, dp(6)));
        LinearLayout.LayoutParams searchLp = new LinearLayout.LayoutParams(0, dp(42), 1);
        searchLp.setMargins(dp(8), 0, dp(8), 0);
        header.addView(searchInput, searchLp);

        TextView messages = new TextView(this);
        messages.setText("💬");
        messages.setTextSize(24);
        messages.setGravity(Gravity.CENTER);
        messages.setContentDescription("Messaging");
        header.addView(messages, new LinearLayout.LayoutParams(dp(42), dp(42)));
        return header;
    }

    private LinearLayout bottomNav() {
        LinearLayout nav = new LinearLayout(this);
        nav.setOrientation(LinearLayout.HORIZONTAL);
        nav.setGravity(Gravity.CENTER);
        nav.setPadding(0, dp(6), 0, dp(4));
        nav.setBackgroundColor(Color.WHITE);
        nav.addView(navItem("⌂\nHome", true));
        nav.addView(navItem("👥\nNetwork", false));
        nav.addView(navItem("＋\nPost", false));
        nav.addView(navItem("🔔\nAlerts", false));
        nav.addView(navItem("💼\nJobs", false));
        return nav;
    }

    private TextView navItem(String text, boolean active) {
        TextView item = new TextView(this);
        item.setText(text);
        item.setGravity(Gravity.CENTER);
        item.setTextSize(11);
        item.setTextColor(active ? TEXT : MUTED);
        item.setTypeface(active ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
        item.setOnClickListener(v -> showHome());
        item.setContentDescription(text.replace("\n", " "));
        item.setLayoutParams(new LinearLayout.LayoutParams(0, dp(54), 1));
        return item;
    }

    private LinearLayout startPostCard() {
        LinearLayout card = card();
        card.setPadding(dp(14), dp(10), dp(14), dp(8));
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.addView(avatar("M", dp(42)));
        TextView prompt = new TextView(this);
        prompt.setText("Start a professional update");
        prompt.setTextColor(MUTED);
        prompt.setTextSize(15);
        prompt.setGravity(Gravity.CENTER_VERTICAL);
        prompt.setPadding(dp(14), 0, 0, 0);
        prompt.setBackground(rounded(Color.WHITE, BORDER, dp(24)));
        LinearLayout.LayoutParams promptLp = new LinearLayout.LayoutParams(0, dp(44), 1);
        promptLp.setMargins(dp(10), 0, 0, 0);
        row.addView(prompt, promptLp);
        card.addView(row);

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setGravity(Gravity.CENTER);
        actions.addView(compactAction("📷 Media"));
        actions.addView(compactAction("🗓 Event"));
        actions.addView(compactAction("✍ Write"));
        card.addView(actions);
        return card;
    }

    private void seedPeople() {
        people.add(new Person("Amit Sharma", "Founder", "TechCorp"));
        people.add(new Person("Priya Mehta", "HR Manager", "PeopleOps"));
        people.add(new Person("Rahul Singh", "Software Engineer", "BuildAI"));
        people.add(new Person("Neha Kapoor", "Product Manager", "ScaleLabs"));
        people.add(new Person("Daniel Lee", "Data Scientist", "InsightWorks"));
    }

    private void renderFeed() {
        feedList.removeAllViews();
        for (int i = 0; i < 30; i++) {
            Person p = people.get(i % people.size());
            LinearLayout card = card();
            card.setId(R.id.post_card);
            card.setContentDescription("Post by " + p.name);
            card.setOnClickListener(v -> showProfile(p));

            LinearLayout header = new LinearLayout(this);
            header.setOrientation(LinearLayout.HORIZONTAL);
            header.setGravity(Gravity.CENTER_VERTICAL);
            header.setId(R.id.feed_profile_link);
            header.setContentDescription("Open feed profile " + p.name);
            header.setClickable(true);
            header.setOnClickListener(v -> showProfile(p));
            header.addView(avatar(initials(p.name), dp(48)));
            LinearLayout identity = new LinearLayout(this);
            identity.setOrientation(LinearLayout.VERTICAL);
            identity.setPadding(dp(10), 0, 0, 0);
            identity.setContentDescription("Open feed profile " + p.name);
            identity.setClickable(true);
            identity.setOnClickListener(v -> showProfile(p));
            TextView authorName = addText(identity, p.name, 16, true, TEXT);
            authorName.setId(R.id.feed_profile_link);
            authorName.setContentDescription("Open feed profile " + p.name);
            authorName.setClickable(true);
            authorName.setOnClickListener(v -> showProfile(p));
            addText(identity, p.title + " at " + p.company, 12, false, MUTED);
            addText(identity, (i + 1) + "h • Mock visibility", 12, false, MUTED);
            header.addView(identity, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
            TextView menu = new TextView(this);
            menu.setText("⋯");
            menu.setTextSize(26);
            menu.setTextColor(MUTED);
            menu.setGravity(Gravity.CENTER);
            header.addView(menu, new LinearLayout.LayoutParams(dp(36), dp(36)));
            card.addView(header);

            TextView body = addText(card, postText(i), 15, false, TEXT);
            body.setPadding(0, dp(10), 0, dp(10));

            TextView metrics = addText(card, "👍 " + (18 + i * 3) + " reactions • " + (i % 5) + " comments", 12, false, MUTED);
            metrics.setPadding(0, 0, 0, dp(6));

            View divider = new View(this);
            divider.setBackgroundColor(BORDER);
            card.addView(divider, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));

            LinearLayout actionRow = new LinearLayout(this);
            actionRow.setOrientation(LinearLayout.HORIZONTAL);
            actionRow.setGravity(Gravity.CENTER);
            Button like = feedAction("Like");
            like.setId(R.id.like_button);
            like.setContentDescription("Like");
            like.setOnClickListener(v -> {
                Button b = (Button) v;
                b.setText("Liked");
                b.setContentDescription("Liked");
                b.setTextColor(BLUE);
            });
            actionRow.addView(like);
            actionRow.addView(feedAction("Comment"));
            actionRow.addView(feedAction("Share"));
            actionRow.addView(feedAction("Send"));
            card.addView(actionRow);
            feedList.addView(card);
        }
    }

    private String postText(int i) {
        String[] posts = {
                "A quick note from today’s build: small teams move faster when context is written down and decisions are easy to find.",
                "Hiring works better when the role, expectations, and interview loop are explicit from day one.",
                "Automation demos should start in controlled mock environments before touching production workflows.",
                "Good outreach starts with relevance, context, and respect — not volume.",
                "A reliable workflow beats a flashy one-off script every time. Repeatability is the product."
        };
        return posts[i % posts.length];
    }

    private void renderResults(String query) {
        String needle = query.trim().toLowerCase();
        resultsList.removeAllViews();
        profilePage.setVisibility(View.GONE);
        if (needle.isEmpty()) {
            feedList.setVisibility(View.VISIBLE);
            return;
        }
        feedList.setVisibility(View.GONE);
        for (Person p : people) {
            if (p.name.toLowerCase().contains(needle) || p.company.toLowerCase().contains(needle)) {
                LinearLayout row = card();
                row.setId(R.id.person_result);
                row.setContentDescription("Person result " + p.name);
                row.setOrientation(LinearLayout.HORIZONTAL);
                row.setGravity(Gravity.CENTER_VERTICAL);
                row.addView(avatar(initials(p.name), dp(52)));
                LinearLayout details = new LinearLayout(this);
                details.setOrientation(LinearLayout.VERTICAL);
                details.setPadding(dp(12), 0, 0, 0);
                TextView name = addText(details, p.name, 17, true, TEXT);
                name.setId(R.id.person_result);
                name.setContentDescription("Open profile " + p.name);
                TextView meta = addText(details, p.title + " at " + p.company, 14, false, MUTED);
                TextView sub = addText(details, "2nd • Professional network mock profile", 12, false, MUTED);
                row.addView(details, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
                Button connectMini = outlineButton("Connect");
                row.addView(connectMini, new LinearLayout.LayoutParams(dp(118), dp(42)));
                View.OnClickListener open = v -> showProfile(p);
                row.setOnClickListener(open);
                name.setOnClickListener(open);
                meta.setOnClickListener(open);
                sub.setOnClickListener(open);
                resultsList.addView(row);
            }
        }
    }

    private void showProfile(Person p) {
        feedList.setVisibility(View.GONE);
        resultsList.removeAllViews();
        profilePage.removeAllViews();
        profilePage.setVisibility(View.VISIBLE);

        LinearLayout hero = card();
        hero.setPadding(0, 0, 0, dp(14));
        TextView cover = new TextView(this);
        cover.setText(" ");
        cover.setBackgroundColor(Color.rgb(191, 219, 254));
        hero.addView(cover, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(92)));

        TextView avatar = avatar(initials(p.name), dp(86));
        LinearLayout.LayoutParams avatarLp = new LinearLayout.LayoutParams(dp(86), dp(86));
        avatarLp.setMargins(dp(16), dp(-42), 0, 0);
        hero.addView(avatar, avatarLp);

        LinearLayout info = new LinearLayout(this);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(dp(16), dp(8), dp(16), 0);
        addText(info, p.name, 24, true, TEXT);
        addText(info, p.title + " at " + p.company, 16, false, Color.rgb(45, 45, 45));
        addText(info, "India • 500+ mock connections", 13, false, MUTED);
        addText(info, "Open to relevant professional conversations", 13, false, BLUE);

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        buttons.setPadding(0, dp(12), 0, 0);
        Button connect = filledButton("Connect");
        connect.setId(R.id.connect_button);
        connect.setContentDescription("Connect");
        connect.setOnClickListener(v -> {
            Button b = (Button) v;
            b.setText("Connected");
            b.setContentDescription("Connected");
        });
        buttons.addView(connect, new LinearLayout.LayoutParams(0, dp(46), 1));
        Button message = outlineButton("Message");
        LinearLayout.LayoutParams msgLp = new LinearLayout.LayoutParams(0, dp(46), 1);
        msgLp.setMargins(dp(8), 0, 0, 0);
        buttons.addView(message, msgLp);
        info.addView(buttons);
        hero.addView(info);
        profilePage.addView(hero);

        LinearLayout about = card();
        addText(about, "About", 18, true, TEXT);
        addText(about, "This is a controlled native mock profile for QA automation. It mirrors common professional-network UI patterns without using any real platform branding.", 14, false, TEXT);
        profilePage.addView(about);
    }

    private void showHome() {
        searchInput.setText("");
        resultsList.removeAllViews();
        profilePage.setVisibility(View.GONE);
        feedList.setVisibility(View.VISIBLE);
    }

    private LinearLayout card() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(14), dp(12), dp(14), dp(12));
        card.setBackground(rounded(Color.WHITE, BORDER, dp(0)));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        lp.setMargins(0, 0, 0, dp(8));
        card.setLayoutParams(lp);
        return card;
    }

    private TextView addText(LinearLayout parent, String text, int sp, boolean bold, int color) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(sp);
        tv.setTextColor(color);
        tv.setPadding(0, dp(2), 0, dp(2));
        if (bold) tv.setTypeface(Typeface.DEFAULT_BOLD);
        parent.addView(tv);
        return tv;
    }

    private TextView avatar(String text, int size) {
        TextView avatar = new TextView(this);
        avatar.setText(text);
        avatar.setTextColor(Color.WHITE);
        avatar.setTextSize(size > dp(60) ? 26 : 16);
        avatar.setTypeface(Typeface.DEFAULT_BOLD);
        avatar.setGravity(Gravity.CENTER);
        avatar.setBackground(oval(BLUE));
        avatar.setLayoutParams(new LinearLayout.LayoutParams(size, size));
        return avatar;
    }

    private Button feedAction(String text) {
        Button button = new Button(this);
        button.setText(text);
        button.setTextColor(MUTED);
        button.setTextSize(12);
        button.setAllCaps(false);
        button.setBackgroundColor(Color.TRANSPARENT);
        button.setLayoutParams(new LinearLayout.LayoutParams(0, dp(48), 1));
        return button;
    }

    private TextView compactAction(String text) {
        TextView action = new TextView(this);
        action.setText(text);
        action.setTextSize(12);
        action.setGravity(Gravity.CENTER);
        action.setTextColor(MUTED);
        action.setLayoutParams(new LinearLayout.LayoutParams(0, dp(42), 1));
        return action;
    }

    private Button filledButton(String text) {
        Button button = new Button(this);
        button.setText(text);
        button.setTextColor(Color.WHITE);
        button.setAllCaps(false);
        button.setTypeface(Typeface.DEFAULT_BOLD);
        button.setBackground(rounded(BLUE, BLUE, dp(24)));
        return button;
    }

    private Button outlineButton(String text) {
        Button button = new Button(this);
        button.setText(text);
        button.setTextColor(BLUE);
        button.setAllCaps(false);
        button.setTypeface(Typeface.DEFAULT_BOLD);
        button.setBackground(rounded(Color.WHITE, BLUE, dp(22)));
        return button;
    }

    private GradientDrawable rounded(int fill, int stroke, int radius) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setShape(GradientDrawable.RECTANGLE);
        drawable.setColor(fill);
        drawable.setCornerRadius(radius);
        if (stroke != 0) drawable.setStroke(dp(1), stroke);
        return drawable;
    }

    private GradientDrawable oval(int fill) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setShape(GradientDrawable.OVAL);
        drawable.setColor(fill);
        return drawable;
    }

    private String initials(String name) {
        String[] parts = name.trim().split("\\s+");
        if (parts.length == 1) return parts[0].substring(0, 1).toUpperCase();
        return (parts[0].substring(0, 1) + parts[1].substring(0, 1)).toUpperCase();
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }
}
