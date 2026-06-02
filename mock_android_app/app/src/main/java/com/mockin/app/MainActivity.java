package com.mockin.app;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
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
    private final int BORDER = Color.rgb(220, 220, 220);

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

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(12), dp(10), dp(12), dp(10));
        header.setBackgroundColor(Color.WHITE);

        TextView brand = new TextView(this);
        brand.setText("MockIn");
        brand.setTextColor(BLUE);
        brand.setTextSize(22);
        brand.setTypeface(Typeface.DEFAULT_BOLD);
        header.addView(brand, new LinearLayout.LayoutParams(dp(88), LinearLayout.LayoutParams.WRAP_CONTENT));

        searchInput = new EditText(this);
        searchInput.setId(R.id.search_input);
        searchInput.setHint("Search people");
        searchInput.setSingleLine(true);
        searchInput.setContentDescription("Search people");
        searchInput.setTextSize(15);
        searchInput.setPadding(dp(14), 0, dp(14), 0);
        header.addView(searchInput, new LinearLayout.LayoutParams(0, dp(46), 1));

        Button home = new Button(this);
        home.setId(R.id.home_button);
        home.setText("Home");
        home.setContentDescription("Home");
        home.setOnClickListener(v -> showHome());
        header.addView(home, new LinearLayout.LayoutParams(dp(86), dp(46)));

        root.addView(header);

        ScrollView scroll = new ScrollView(this);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(10), dp(10), dp(10), dp(24));

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

        searchInput.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) { renderResults(s.toString()); }
            @Override public void afterTextChanged(Editable s) {}
        });

        return root;
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
            addText(card, p.name, 16, true, Color.rgb(31, 41, 55));
            addText(card, p.title + " at " + p.company, 13, false, Color.rgb(107, 114, 128));
            addText(card, postText(i), 15, false, Color.rgb(31, 41, 55));
            Button like = pillButton("Like");
            like.setId(R.id.like_button);
            like.setContentDescription("Like");
            like.setOnClickListener(v -> {
                Button b = (Button) v;
                b.setText("Liked");
                b.setContentDescription("Liked");
            });
            card.addView(like, new LinearLayout.LayoutParams(dp(110), dp(44)));
            feedList.addView(card);
        }
    }

    private String postText(int i) {
        String[] posts = {
                "Sharing a quick lesson from building products with small teams.",
                "Hiring is easier when communication and expectations are explicit.",
                "Automation demos should start in controlled test environments.",
                "Good outreach starts with relevance, context, and respect.",
                "A reliable workflow is better than a flashy one-off script."
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
                addText(row, p.name, 17, true, Color.rgb(31, 41, 55));
                addText(row, p.title + " at " + p.company, 14, false, Color.rgb(107, 114, 128));
                row.setOnClickListener(v -> showProfile(p));
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
        addText(hero, p.name, 24, true, Color.rgb(31, 41, 55));
        addText(hero, p.title + " at " + p.company, 16, false, Color.rgb(75, 85, 99));
        TextView pill = addText(hero, "Open to relevant professional conversations", 13, false, Color.rgb(55, 48, 163));
        pill.setPadding(dp(8), dp(8), dp(8), dp(8));
        Button connect = pillButton("Connect");
        connect.setId(R.id.connect_button);
        connect.setContentDescription("Connect");
        connect.setOnClickListener(v -> {
            Button b = (Button) v;
            b.setText("Connected");
            b.setContentDescription("Connected");
        });
        hero.addView(connect, new LinearLayout.LayoutParams(dp(140), dp(46)));
        profilePage.addView(hero);
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
        card.setBackgroundColor(Color.WHITE);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        lp.setMargins(0, 0, 0, dp(12));
        card.setLayoutParams(lp);
        return card;
    }

    private TextView addText(LinearLayout parent, String text, int sp, boolean bold, int color) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(sp);
        tv.setTextColor(color);
        tv.setPadding(0, dp(3), 0, dp(3));
        if (bold) tv.setTypeface(Typeface.DEFAULT_BOLD);
        parent.addView(tv);
        return tv;
    }

    private Button pillButton(String text) {
        Button button = new Button(this);
        button.setText(text);
        button.setTextColor(BLUE);
        button.setAllCaps(false);
        return button;
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }
}
