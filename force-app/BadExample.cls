public class BadExample {
    public void Process_Accounts(List<Account> accounts) {
        for (Account a : accounts) {
            List<Contact> cons = [SELECT Id FROM Contact WHERE AccountId = :a.Id];
        }
        Account special = [SELECT Id FROM Account WHERE Id = '0015g00000AbCdEfGH'];
    }
}
