Hi -

Today i would like to provide a walkthrough of the open source drydock software I announced earlier this month.

Drydock uses Nautical Terminology - I call it the SAIL method. You - The operator are the product owner or Commander and the LLM is development team or Crew.

Drydock is a hardened pipeline for building software from specification using and Agile and Test Driven Development.  Agile and TDD are well documented processes that your LLM fully understands. That means your Crew follows the same Software methedology you have have used for years to convert large specifications into stories you can be accurately built. Most watchers of this video will easily understand what it does.

Agile and Test First Development enables your Crew to reproducably build working software using smaller LLM models. In fact Drydock is only tested on smaller models to ensure the process is solid.

After building your working software, drydock lets you maintain it using change tickets and specification edits.

Finally, Drydock supports Rigging or enterprise governance - your branding and best practices are followed. It conforms your projects while building them to your Business Rules.

I believe drydock is unique in the Specification Driven Development space - it Builds working software
AND it lets you maintain and update your software.

Drydock is Full Software Development Lifecycle tooling that builds large projects in a cost optimized way.

# CHANGE

This slide shows the Drydock process...  You should recognize it

This IS a model of an Agile Test First Development process

In step 1 we import an Epic - which can be composed of incomplete or messy specifications.  We then run an analyze step to understand the input - in Agile this is Epic RefinemInt and Story Decomposition.

The LLM uses questionaires in our dedicated web console to decompose the epic into stories.  At the end of this phase your crew is ready to Groom and plan the build.

The next phase is planning.  Here the crew will Groom the stories, add deterministic Acceptance Criteria, and create a dependency graph database called the Manifest that relates your stories. your Crew understands, for example, that delivering a web page will require story to create database tables, a story to populate that data, a story to creates the rest route, and finally a story to build the web page.

Everything is visible to the user in a Web Console called the Quarterdeck where the data is formatted for you.

The Build phase creates working software in a context aware process that groups your stories into features designed to save context.

Stories are only considered built when their acceptance criteria is tested and passes.  Only the story that passes its Definition of Done is considered built correctly which allows the build move on to the next feature block.  The build process has many nice features like automated context compression and has retry logic if the first pass does not meet all deterministic acceptacne criteria.

Once built, we score the project using project acceptance criteria to ensure that it meets the project goals.

Finally dyrdock maintains your software using change tickets or specificaiton edits.

# CHANGE
