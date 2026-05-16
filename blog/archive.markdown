---
layout: page
title: Blog archive
subtitle: Older posts kept for reference. NBI has changed since they were written.
permalink: /blog/archive/
---

<div class="callout callout--warn">
  <p class="callout__title">These posts are historical.</p>
  <p>The product they describe — single-provider, Copilot-only NBI — is several major releases behind. For current information, see the <a href="{{ '/' | relative_url }}">home page</a> or the <a href="https://github.com/notebook-intelligence/notebook-intelligence/blob/main/CHANGELOG.md">CHANGELOG</a>.</p>
</div>

<ul class="post-list">
  {% assign archived_posts = site.posts | where: "archived", true %}
  {% for post in archived_posts %}
    <li class="post-list__item">
      <p class="post-list__date"><time datetime="{{ post.date | date_to_xmlschema }}">{{ post.date | date: "%B %-d, %Y" }}</time></p>
      <h2 class="post-list__title"><a href="{{ post.url | relative_url }}">{{ post.title | escape }}</a></h2>
      <p class="post-list__excerpt">{{ post.excerpt | strip_html | truncatewords: 32 }}</p>
    </li>
  {% endfor %}
</ul>
