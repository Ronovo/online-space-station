"""Careers: the job ladder, the salary, and what a finished round does to the save.

A save holds the account's career and the round in progress, side by side:
    career   {"name", "credits", "rounds", "revives", "unlocked", "captain", "pick_owed", "files"}, or None before
             one is started or after it ends. unlocked lists the regular jobs it may start a shift in, captain says
             whether it has played a shift as Head of Personnel, pick_owed that it may choose a job to unlock, and
             files holds what is on its computer (see pda), which every shift starts with and hands back
    shift    the player_data of the round in progress, or None between rounds
    summary  what the last round came to, shown once it ends
Single rounds use the shift on its own and leave the career alone.
"""

import copy

from space_online.game.character_methods.character_creation import JOBS, STARTING_FILES, clean_name, new_shift
from space_online.game.helper_methods.antagonists import threat_report
from space_online.game.helper_methods.game_clock import get_elapsed_seconds
from space_online.game.helper_methods.rounds import CAREER, round_over
from space_online.game.helper_methods.stock_market import round_credits

START_JOB = "Staff Assistant"
HEAD_JOB = "Head of Personnel"
TOP_JOB = "Captain"
# The jobs a career unlocks one at a time, in pay order.
REGULAR_JOBS = tuple(sorted((job for job in JOBS if job not in (START_JOB, HEAD_JOB, TOP_JOB)),
                            key=lambda job: JOBS[job]["credits"]))

PAY_INTERVAL_SECONDS = 10 * 60
# A job's salary per PAY_INTERVAL_SECONDS is its starting credits divided by this.
SALARY_DIVISOR = 10
REVIVE_BASE_COST = 5000
REVIVE_COST_STEP = 1000


def empty_save():
    return {"career": None, "shift": None, "summary": None}


def job_salary(job):
    return JOBS[job]["credits"] // SALARY_DIVISOR


def new_career(name):
    """A career at the bottom of the ladder. Raises ValueError with a player-facing message for a bad name."""
    return {"name": clean_name(name), "credits": JOBS[START_JOB]["credits"], "rounds": 0, "revives": 0,
            "unlocked": [], "captain": False, "pick_owed": False, "files": dict(STARTING_FILES)}


def locked_regular_jobs(career):
    return [job for job in REGULAR_JOBS if job not in career["unlocked"]]


def unlocked_jobs(career):
    """The jobs a career can start a shift in: the regular jobs it has unlocked, the Head of Personnel once it has
    them all, and the Captain once it has played a shift as Head of Personnel."""
    locked = locked_regular_jobs(career)
    jobs = [START_JOB, *(job for job in REGULAR_JOBS if job not in locked)]
    if not locked:
        jobs.append(HEAD_JOB)
    if career["captain"]:
        jobs.append(TOP_JOB)
    return jobs


def unlock_job(career, job):
    """Spend the pick a round that ended without a new job leaves. Raises ValueError with a player-facing message
    when there is no pick or job isn't one to pick."""
    if not career["pick_owed"]:
        raise ValueError("You have no job to pick right now.")
    if job not in locked_regular_jobs(career):
        raise ValueError("Pick one of the jobs you haven't unlocked yet.")
    career["unlocked"].append(job)
    career["pick_owed"] = False


def revive_cost(career):
    return REVIVE_BASE_COST + REVIVE_COST_STEP * career["revives"]


def start_career_shift(career, job):
    """The player_data for a career's next round. Raises ValueError if the career hasn't unlocked job."""
    if job not in unlocked_jobs(career):
        raise ValueError("Your career hasn't unlocked that job yet.")
    shift = new_shift(career["name"], job, mode=CAREER, credits=career["credits"])
    shift["files"] = copy.deepcopy(career["files"])
    return shift


def pay_salary(game):
    """Pay a career's salary for every pay interval that has gone by, at the rate of the job held now. The pay
    stops once the shuttle has left the station."""
    player_data = game.player_data
    round_ = player_data["round"]
    if round_["mode"] != CAREER or round_over(player_data) or round_["shuttle"]["state"] == "transit":
        return
    due = int((get_elapsed_seconds(player_data) - round_["paid_through"]) // PAY_INTERVAL_SECONDS)
    if due <= 0:
        return
    pay = due * job_salary(player_data["job"])
    round_["paid_through"] += due * PAY_INTERVAL_SECONDS
    round_["salary_paid"] += pay
    player_data["credits"] += pay
    game.alert("Payday", f"Your {player_data['job']} salary has been paid: {pay} credits.")
    game.add_note(f"Paid {pay} credits in salary.")


def _cash_out(shift):
    """Sell every share held at the current price. Returns the credits raised."""
    prices = {company["name"]: company["current_value"] for company in shift["stock_market"]["companies"]}
    raised = sum(shares * prices.get(name, 0) for name, shares in shift["stock_holdings"].items())
    shift["stock_holdings"] = {}
    return round_credits(raised)


def _settle_career(career, shift, summary):
    """Carry a finished round into the career: credits, the price of dying, and what it unlocks.

    Ending the round in a regular job the career hasn't unlocked unlocks it. Ending it in any other job, while
    regular jobs are still locked, leaves the career a pick of one.

    Returns the career, or None when it has ended.
    """
    career["credits"] = summary["credits"]
    career["files"] = shift["files"]
    if not summary["survived"]:
        cost = revive_cost(career)
        if career["credits"] < cost:
            summary["career_over"] = True
            return None
        career["credits"] = round_credits(career["credits"] - cost)
        career["revives"] += 1
        summary["revive_cost"] = cost
        summary["credits"] = career["credits"]

    before = unlocked_jobs(career)
    career["rounds"] += 1
    locked = locked_regular_jobs(career)
    if shift["job"] in locked:
        career["unlocked"].append(shift["job"])
    elif locked:
        career["pick_owed"] = True
    if shift["round"]["job_at_start"] == HEAD_JOB:
        career["captain"] = True
    summary["unlocked"] = [job for job in unlocked_jobs(career) if job not in before]
    summary["pick_owed"] = career["pick_owed"]
    return career


def finish_round(save):
    """Close the round in save["shift"]: write its summary, settle the career, and clear the shift."""
    shift = save["shift"]
    round_ = shift["round"]
    outcome = round_["outcome"]
    shares = _cash_out(shift)
    summary = {
        "mode": round_["mode"],
        "name": shift["name"],
        "job": round_["job_at_start"],
        "ended_as": shift["job"] if shift["job"] != round_["job_at_start"] else None,
        "survived": outcome["survived"],
        "cause": outcome["cause"],
        "minutes": int(outcome["seconds"] // 60),
        "threats": threat_report(shift),
        "salary": round_["salary_paid"],
        "duties_done": round_["duties_done"],
        "duties_missed": round_["duties_missed"],
        "shares": shares,
        "credits": round_credits(shift["credits"] + shares),
        "revive_cost": None,
        "career_over": False,
        "unlocked": [],
        "pick_owed": False,
    }
    if round_["mode"] == CAREER:
        save["career"] = _settle_career(save["career"], shift, summary)
    save["shift"] = None
    save["summary"] = summary
    return summary
