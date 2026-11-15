# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Homeowners and anyone at home who has repetitive chores (taking out the trash, changing a bulb, wiping a surface) and would like a robot to do them. They arrive curious, not technical: they describe a job in plain words and expect the product to work out the rest.

## Product Purpose

Nothingburger designs a robot for one household chore. The user names the job; if the motion and grip aren't known yet, they demonstrate it once with a Meta Quest headset and pressure-sensor gloves; agents then pick the robot's base, arms and gripper from a parts catalog and explain why each part won. Success is a user who leaves with a robot design they understand, for a job in their own space.

## Positioning

The robot is designed from the user's own demonstration and their real space (a Matterport scan), not picked from a fixed product line. Every part choice comes with its reason and the runner-up it beat.

## Operating Context

- The site has two parts: a landing page that explains the idea, and the studio, where the user is inside a real 3D space and plans a job.
- The showcase space is Princeton's Julis Romo Rabinowitz (JRR) Hall: the inside is the CoStar team's Matterport tour (model `2K7G7cdukZV`, embed only, our API key cannot download its mesh); there is no Matterport or Vexcel 3D model of the outside.
- Demonstrations are recorded on the Quest; the studio talks to the Pathfinder backend (`world/pathfinder/backend`, port 8004) and the design agent (`agent/`).

## Capabilities and Constraints

- Plain HTML, CSS and JavaScript, no build step; Three.js from a CDN import map.
- Studio steps: the job, the plan, show it once (headset), the robot, watch it work, parts that fit.
- A code-drawn sample apartment stays available in the studio as a secondary space (it hosts "watch it work").
- The planner behind `POST /plan` is still a stand-in; the design agent is not yet served over HTTP.
- Matterport Showcase SDK key works on localhost only.

## Brand Commitments

- Name: Nothingburger (renamed from Gold Bears, 2026-11-14; the gold, ink and paper colours and the bear mark stay for now). Line: "Automate your life".
- The landing opens on a 3D model of JRR Hall's exterior on a blueprint landscape; scrolling orbits the building and ends by entering the main hall (user's direction, 2026-11-14).

## Evidence on Hand

- Real: the JRR Hall Matterport tour, the 5836 La Mirada Ave scan and Vexcel models, the parts catalog (`agent/design_flow/catalog.py`), sample demonstration recordings (`capture/samples/`).
- None yet: customers, testimonials, pricing, benchmarks. Do not invent them.

## Product Principles

1. Plain words in, a robot out: the user never needs robotics vocabulary.
2. Show your work: every design choice carries its reason and what it beat.
3. Real spaces over renders: the user's actual space (a scan) is the stage.
4. Simulated numbers are never presented as measured facts.
