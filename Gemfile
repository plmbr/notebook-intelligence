source "https://rubygems.org"

# Jekyll site for notebook-intelligence.github.io.
#
# Build locally:
#   bundle install
#   bundle exec jekyll serve
#
# Deploys via GitHub Pages on push to gh-pages. We pin against the
# github-pages gem so the local build matches the deployed build; the
# plugins listed in :jekyll_plugins below are all on the GitHub Pages
# safelist (https://pages.github.com/versions/).

gem "github-pages", "~> 232", group: :jekyll_plugins

group :jekyll_plugins do
  gem "jekyll-seo-tag"
  gem "jekyll-sitemap"
  gem "jekyll-feed"
  gem "jekyll-redirect-from"
end

platforms :mingw, :x64_mingw, :mswin, :jruby do
  gem "tzinfo", ">= 1", "< 3"
  gem "tzinfo-data"
end

gem "wdm", "~> 0.1", :platforms => [:mingw, :x64_mingw, :mswin]
gem "http_parser.rb", "~> 0.6.0", :platforms => [:jruby]
