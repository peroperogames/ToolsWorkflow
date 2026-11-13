from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_pending_review.py")
t = p.read_text(encoding="utf-8")
old = """        review = {"id": 500 + self.created, "state": "PENDING",
                  "commit_id": commit_id, "user": BOT}
        self.reviews.append(review)
        return review"""
new = """        review = {"id": 500 + self.created, "state": "PENDING",
                  "commit_id": commit_id, "user": BOT}
        self.reviews.append(review)
        self.last_review_id = review["id"]
        return review"""
assert t.count(old) == 1
t = t.replace(old, new)

old2 = """        return [
            {"id": 901 + index, "pull_request_review_id": 555}
            for index in range(len(self.added))
        ]"""
new2 = """        return [
            {"id": 901 + index, "pull_request_review_id": getattr(self, "last_review_id", 555)}
            for index in range(len(self.added))
        ]"""
assert t.count(old2) == 1
t = t.replace(old2, new2)
p.write_text(t, encoding="utf-8", newline="\n")
print("patched")
