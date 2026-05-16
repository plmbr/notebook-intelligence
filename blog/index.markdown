---
layout: page
title: Blog
subtitle: Release notes and the occasional deep dive.
permalink: /blog/
---

<ul class="post-list">
  {% assign current_posts = site.posts | where_exp: "p", "p.archived != true" %}
  {% for post in current_posts %}
    <li class="post-list__item">
      <p class="post-list__date"><time datetime="{{ post.date | date_to_xmlschema }}">{{ post.date | date: "%B %-d, %Y" }}</time></p>
      <h2 class="post-list__title"><a href="{{ post.url | relative_url }}">{{ post.title | escape }}</a></h2>
      {% if post.description %}
        <p class="post-list__excerpt">{{ post.description | escape }}</p>
      {% else %}
        <p class="post-list__excerpt">{{ post.excerpt | strip_html | truncatewords: 32 }}</p>
      {% endif %}
    </li>
  {% endfor %}
</ul>

<p style="margin-top: var(--space-12); color: var(--ink-500); font-size: var(--fs-sm);">
  Older posts from 2025 have been moved to the <a href="{{ '/blog/archive/' | relative_url }}">blog archive</a>.
</p>
