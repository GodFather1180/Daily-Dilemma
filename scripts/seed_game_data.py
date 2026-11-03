from typing import List, Tuple

from sqlalchemy.orm import Session

from shared.database import get_db
from game.models import Scenario, ScenarioOption
from user_service.v1.models.user import Base  # shared metadata used by game models

# -------------------------------------------------------
# SCENARIO DATA
#
# Each option: (key, text, is_baseline_majority)
#
# To run this script:
#   docker compose exec web python scripts/seed_game_data.py
# -------------------------------------------------------

#
# if deleted a scenario from here, it will remain in the DB. Manual cleanup needed.
#
SCENARIOS: List[dict] = [
    {
        "slug": "bus-seat",
        "text": "You are on a crowded bus and an elderly person gets on.",
        "options": [
            ("A", "You give up your seat.", True),
            ("B", "You pretend not to notice.", False),
        ],
    },
    {
        "slug": "exam-cheating",
        "text": "You see another student cheating during an exam and"
        " the instructor doesn't notice.",
        "options": [
            ("A", "Tell the instructor right away.", True),
            ("B", "Do nothing. It's not your problem.", False),
            ("C", "Talk to the student after the exam.", False),
        ],
    },
    {
        "slug": "line-cutter",
        "text": "Someone cuts ahead of you in a grocery store line.",
        "options": [
            ("A", "Politely tell them there is a line.", False),
            ("B", "Say nothing and just let it go.", True),
            ("C", "Complain loudly so others hear.", False),
        ],
    },
    {
        "slug": "lost-wallet",
        "text": "You find a wallet on the ground with ID and cash inside.",
        "options": [
            ("A", "Try to contact the owner and return everything.", True),
            ("B", "Turn it in to a nearby store or police station.", False),
            ("C", "Take the cash and leave the wallet.", False),
        ],
    },
    {
        "slug": "group-project",
        "text": "A teammate did nothing for a group project and the deadline is today.",
        "options": [
            ("A", "Report their lack of work to the instructor.", False),
            ("B", "Submit the project and say nothing about it.", True),
            ("C", "Do a partial report so they lose some marks.", False),
        ],
    },
    {
        "slug": "elevator-door",
        "text": "You are in an elevator and"
        " see someone rushing toward the closing doors.",
        "options": [
            ("A", "Hold the door open for them.", True),
            ("B", "Let the doors close and pretend not to see.", False),
            ("C", "Avoid eye contact and press close faster.", False),
        ],
    },
    {
        "slug": "restaurant-tip",
        "text": "Service at a restaurant was slow and the server was a bit rude.",
        "options": [
            ("A", "Still tip 15% or more out of habit.", False),
            ("B", "Tip a smaller amount than usual.", True),
            ("C", "Leave no tip at all.", False),
        ],
    },
    {
        "slug": "borrowed-charger",
        "text": "Friend says they'll borrow your charger for a minute but takes it"
        " forever.",
        "options": [
            ("A", "Text them right away to remind them.", True),
            ("B", "Wait and see if they remember later.", False),
            ("C", "Say nothing and just buy a new one.", False),
        ],
    },
    {
        "slug": "noisy-neighbor",
        "text": "Your neighbour plays loud music late at night multiple times a week.",
        "options": [
            ("A", "Talk to them politely about the noise.", True),
            ("B", "Immediately file a complaint with building management.", False),
            ("C", "Do nothing and just put on headphones.", False),
        ],
    },
    {
        "slug": "shopping-cart",
        "text": "You finish unloading groceries in a parking lot with scattered carts.",
        "options": [
            ("A", "Return your cart to the cart corral.", True),
            ("B", "Leave it in an empty parking spot.", False),
            ("C", "Prop it up on a curb somewhere nearby.", False),
        ],
    },
    {
        "slug": "sneezing-stranger",
        "text": "A stranger near you on the bus sneezes loudly without covering.",
        "options": [
            ("A", "Say something about covering their mouth.", False),
            ("B", "Quietly move a bit farther away.", True),
            ("C", "Ignore it and stay where you are.", False),
        ],
    },
    {
        "slug": "airplane-armrest",
        "text": "On a flight, you and a stranger both seem to want the middle armrest.",
        "options": [
            ("A", "Take the armrest and keep it.", False),
            ("B", "Share it and adjust so you both have some space.", True),
            ("C", "Avoid using it at all.", False),
        ],
    },
    {
        "slug": "oversharing-friend",
        "text": "A friend vents to you every day and"
        " you're feeling emotionally drained.",
        "options": [
            ("A", "Tell them honestly you need some space.", True),
            ("B", "Keep listening even though it stresses you out.", False),
            ("C", "Start avoiding their messages without explanation.", False),
        ],
    },
    {
        "slug": "found-usb",
        "text": "You find a random USB drive left in the library.",
        "options": [
            ("A", "Plug it into your laptop to see what's inside.", False),
            ("B", "Turn it in to the library front desk.", True),
            ("C", "Throw it away so no one misuses it.", False),
        ],
    },
    {
        "slug": "sharing-answers",
        "text": "Classmate asks for your assignment answers right before the deadline.",
        "options": [
            ("A", "Share your full answers with them.", False),
            ("B", "Refuse and tell them to talk to the instructor.", True),
            ("C", "Give vague hints but not full solutions.", False),
        ],
    },
    {
        "slug": "public-phone-call",
        "text": "Someone is speaking very loudly on their phone in a quiet bus.",
        "options": [
            ("A", "Ask them politely to lower their voice.", False),
            ("B", "Put in headphones or move seats.", True),
            ("C", "Shush them loudly in front of everyone.", False),
        ],
    },
    {
        "slug": "takeout-wrong-order",
        "text": "Your takeout order is slightly wrong but still okay to eat.",
        "options": [
            ("A", "Go back or call to get it fixed.", False),
            ("B", "Let it go and just eat it.", True),
            ("C", "Leave a bad review online.", False),
        ],
    },
    {
        "slug": "dropping-trash",
        "text": "You see someone drop trash on the ground and walk away.",
        "options": [
            ("A", "Pick it up and throw it away yourself.", True),
            ("B", "Call them out for littering.", False),
            ("C", "Ignore it and keep walking.", False),
        ],
    },
    {
        "slug": "loud-chewer",
        "text": "Your friend is chewing loudly during a movie at your place.",
        "options": [
            ("A", "Ignore it and try to focus on the movie.", False),
            ("B", "Lightly joke or hint about the noise.", True),
            ("C", "Pause the movie and directly criticize them.", False),
        ],
    },
    {
        "slug": "dog-off-leash",
        "text": "A friendly dog runs up to you off-leash in a park.",
        "options": [
            ("A", "Pet the dog and look for the owner.", True),
            ("B", "Back away and avoid any contact.", False),
            ("C", "Scold the owner for having the dog off-leash.", False),
        ],
    },
    {
        "slug": "borrowed-money",
        "text": "A friend owes you $30 and keeps avoiding the topic.",
        "options": [
            ("A", "Bring it up directly and ask for the money.", True),
            ("B", "Keep waiting and hope they remember.", False),
            ("C", "Decide to never bring it up again.", False),
        ],
    },
    {
        "slug": "late-arrival-crosswalk",
        "text": "You are late and the crosswalk is red but there are no cars around.",
        "options": [
            ("A", "Wait for the light to turn green.", False),
            ("B", "Quickly cross even though the light is red.", True),
            ("C", "Run to another crossing that looks faster.", False),
        ],
    },
    {
        "slug": "flash-sale-item",
        "text": "There is one item left in a big flash sale and"
        " someone else is eyeing it.",
        "options": [
            ("A", "Grab it quickly before they do.", True),
            ("B", "Let them have it and walk away.", False),
            ("C", "Ask if they want it first.", False),
        ],
    },
    {
        "slug": "talking-in-class",
        "text": "Two people behind you keep talking loudly during lecture.",
        "options": [
            ("A", "Ask them politely to be quiet.", True),
            ("B", "Move to a different seat without saying anything.", False),
            ("C", "Complain about them after class to the instructor.", False),
        ],
    },
    {
        "slug": "free-samples",
        "text": "A store has free samples with a sign that says 'one per person'.",
        "options": [
            ("A", "Take exactly one sample.", True),
            ("B", "Take a few since no one is watching.", False),
            ("C", "Skip the sample entirely.", False),
        ],
    },
    {
        "slug": "overflowing-sink",
        "text": "You see a sink in a public washroom left running and "
        "starting to overflow.",
        "options": [
            ("A", "Turn off the tap and wipe up if needed.", True),
            ("B", "Tell staff but leave it running.", False),
            ("C", "Ignore it and leave.", False),
        ],
    },
    {
        "slug": "apology-text",
        "text": "You snapped at a friend earlier and now feel guilty.",
        "options": [
            ("A", "Send a short apology and explain you were stressed.", True),
            ("B", "Pretend nothing happened and move on.", False),
            ("C", "Over-apologize with a long, dramatic message.", False),
        ],
    },
    {
        "slug": "rideshare-seat",
        "text": "You and two friends get in a ride share;"
        " only the middle seat is left.",
        "options": [
            ("A", "Volunteer to take the middle seat.", True),
            ("B", "Wait silently hoping someone else takes it.", False),
            ("C", "Ask to switch places halfway through.", False),
        ],
    },
    {
        "slug": "messy-kitchen",
        "text": "Your housemate regularly leaves dirty dishes in the shared kitchen.",
        "options": [
            ("A", "Talk to them about dishes and agree on rules.", True),
            ("B", "Clean everything yourself and stay silent.", False),
            ("C", "Leave the mess to prove a point.", False),
        ],
    },
    {
        "slug": "headphone-borrow",
        "text": "A classmate you barely know asks to borrow your headphones.",
        "options": [
            ("A", "Lend them the headphones without worrying.", False),
            ("B", "Politely say you don't share personal items like that.", True),
            ("C", "Ignore the request and pretend you didn't hear.", False),
        ],
    },
    {
        "slug": "ignored-message",
        "text": "You see a message from someone but don't feel like responding yet.",
        "options": [
            ("A", "Open it and reply briefly anyway.", False),
            ("B", "Read it but reply later when you have energy.", True),
            ("C", "Leave it unopened to avoid showing you've seen it.", False),
        ],
    },
]


def get_db_session() -> tuple[Session, any]:
    """Get a real DB session from the shared get_db dependency."""
    db_gen = get_db()
    db = next(db_gen)
    return db, db_gen


def get_or_create_scenario(db: Session, slug: str, text: str) -> Scenario:
    """Find a scenario by slug, or create it if missing."""
    existing = db.query(Scenario).filter_by(slug=slug).one_or_none()
    if existing:
        # If you change text later, you can update it here:
        if existing.text != text:
            existing.text = text
        return existing

    scenario = Scenario(slug=slug, text=text)
    db.add(scenario)
    db.flush()  # populate scenario.id
    return scenario


def upsert_options(
    db: Session,
    scenario: Scenario,
    options: List[Tuple[str, str, bool]],
) -> None:
    """
    For a given scenario, insert or update its options based on (key).
    Does NOT delete old options that aren't listed anymore.
    """
    existing_by_key = {
        opt.key: opt
        for opt in db.query(ScenarioOption).filter_by(scenario_id=scenario.id)
    }

    for key, text, is_baseline in options:
        opt = existing_by_key.get(key)
        if opt:
            if opt.text != text:
                opt.text = text
            if opt.is_baseline_majority != is_baseline:
                opt.is_baseline_majority = is_baseline
            # no need to do anything else if not changed
        else:
            db.add(
                ScenarioOption(
                    scenario_id=scenario.id,
                    key=key,
                    text=text,
                    is_baseline_majority=is_baseline,
                )
            )


def main() -> None:
    db, db_gen = get_db_session()
    try:
        # Make sure all tables exist (for dev / sqlite)
        Base.metadata.create_all(bind=db.get_bind())

        # Seed or update scenarios
        for sc_data in SCENARIOS:
            scenario = get_or_create_scenario(
                db,
                slug=sc_data["slug"],
                text=sc_data["text"],
            )
            upsert_options(db, scenario, sc_data["options"])

        db.commit()
        print("Seeded/updated game scenarios successfully.")

    finally:
        try:
            db.close()
        except Exception:
            pass
        try:
            db_gen.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
